from __future__ import annotations

import argparse
import json
import os
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Tuple

import certifi
import httpx
from dotenv import load_dotenv
from eth_abi import encode
from eth_utils import keccak, to_checksum_address
from py_clob_client_v2.client import ClobClient  # type: ignore
from py_clob_client_v2.clob_types import (  # type: ignore
    AssetType,
    BalanceAllowanceParams,
    BuilderConfig,
)
from py_clob_client_v2.http_helpers import helpers as clob_http_helpers  # type: ignore

from polymarket_auto_claim import PUSD, RelayerApiKeyClient, first_dict


CHAIN_ID = 137
PUSD_DECIMALS = 6
DEFAULT_CLOB_HOST = "https://clob.polymarket.com"


def configure_tls() -> str:
    ca_bundle = os.getenv("CLOB_CA_BUNDLE", "").strip() or certifi.where()
    os.environ.setdefault("SSL_CERT_FILE", ca_bundle)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", ca_bundle)

    # py_clob_client_v2 creates its shared httpx client at import time, so replace it
    # after environment loading to ensure it uses the intended CA bundle.
    try:
        clob_http_helpers._http_client.close()
    except Exception:
        pass
    clob_http_helpers._http_client = httpx.Client(http2=True, verify=ca_bundle)
    return ca_bundle


def amount_to_units(amount: str) -> int:
    try:
        parsed = Decimal(str(amount))
    except InvalidOperation as exc:
        raise ValueError(f"Invalid pUSD amount: {amount}") from exc

    if parsed <= 0:
        raise ValueError("pUSD amount must be greater than 0")

    scaled = parsed * (Decimal(10) ** PUSD_DECIMALS)
    if scaled != scaled.to_integral_value():
        raise ValueError(f"pUSD amount supports at most {PUSD_DECIMALS} decimals: {amount}")
    return int(scaled)


def units_to_amount(value: Any) -> str:
    try:
        units = Decimal(str(value))
    except InvalidOperation:
        return str(value)

    amount = units / (Decimal(10) ** PUSD_DECIMALS)
    return f"{amount.normalize():f}"


def is_address(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        to_checksum_address(value)
        return True
    except Exception:
        return False


def maybe_checksum(value: Any) -> Optional[str]:
    if not is_address(value):
        return None
    return to_checksum_address(str(value))


def first_present(obj: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in obj and obj[key] is not None:
            return obj[key]
    return None


def encode_erc20_approve(spender: str, amount_units: int) -> str:
    selector = keccak(b"approve(address,uint256)")[:4]
    encoded_args = encode(["address", "uint256"], [to_checksum_address(spender), int(amount_units)])
    return "0x" + (selector + encoded_args).hex()


def build_builder_config() -> Optional[BuilderConfig]:
    builder_code = os.getenv("POLY_BUILDER_CODE", "").strip()
    if not builder_code:
        return None
    return BuilderConfig(builder_code=builder_code)


def create_trading_clob_client() -> Any:
    private_key = os.getenv("PRIVATE_KEY", "").strip()
    funder = os.getenv("FUNDER_ADDRESS", "").strip()
    signature_type = int(os.getenv("POLY_SIGNATURE_TYPE", "2"))
    clob_host = (os.getenv("CLOB_HOST", DEFAULT_CLOB_HOST).strip() or DEFAULT_CLOB_HOST).rstrip("/")

    missing = []
    if not private_key:
        missing.append("PRIVATE_KEY")
    if not funder:
        missing.append("FUNDER_ADDRESS")
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

    kwargs: Dict[str, Any] = {
        "host": clob_host,
        "chain_id": CHAIN_ID,
        "key": private_key,
        "signature_type": signature_type,
        "funder": funder,
    }
    builder_config = build_builder_config()
    if builder_config:
        kwargs["builder_config"] = builder_config

    client = ClobClient(**kwargs)
    client.set_api_creds(client.create_or_derive_api_key())
    return client


def collateral_params() -> BalanceAllowanceParams:
    return BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)


def get_collateral_balance_allowance(client: Any) -> Dict[str, Any]:
    return first_dict(client.get_balance_allowance(collateral_params()))


def update_collateral_balance_allowance(client: Any) -> Dict[str, Any]:
    return first_dict(client.update_balance_allowance(collateral_params()))


def extract_allowance_entries(payload: Any) -> List[Tuple[str, Any]]:
    entries: Dict[str, Any] = {}

    def visit(obj: Any) -> None:
        if isinstance(obj, dict):
            spender = (
                obj.get("spender")
                or obj.get("spender_address")
                or obj.get("spenderAddress")
                or obj.get("address")
                or obj.get("contract")
            )
            allowance = first_present(obj, "allowance", "amount", "value", "balance_allowance")
            checked_spender = maybe_checksum(spender)
            if checked_spender and allowance is not None:
                entries[checked_spender] = allowance

            for key, value in obj.items():
                checked_key = maybe_checksum(key)
                if checked_key:
                    if isinstance(value, dict):
                        nested_allowance = first_present(
                            value,
                            "allowance",
                            "amount",
                            "value",
                            "balance_allowance",
                        )
                        entries[checked_key] = nested_allowance if nested_allowance is not None else value
                    else:
                        entries[checked_key] = value
                visit(value)
        elif isinstance(obj, list):
            for item in obj:
                visit(item)

    visit(payload.get("allowances") if isinstance(payload, dict) and "allowances" in payload else payload)
    return sorted(entries.items())


def summarize_balance_allowance(label: str, payload: Dict[str, Any]) -> None:
    print(f"\n[{label}]")
    print(json.dumps(payload, indent=2, ensure_ascii=False))

    balance = payload.get("balance")
    allowance = payload.get("allowance")
    if balance is not None:
        print(f"balance ~= {units_to_amount(balance)} pUSD")
    if allowance is not None:
        print(f"top-level allowance ~= {units_to_amount(allowance)} pUSD")

    entries = extract_allowance_entries(payload)
    if entries:
        print("spender allowances:")
        for spender, raw_allowance in entries:
            print(f"  {spender}: {raw_allowance} ~= {units_to_amount(raw_allowance)} pUSD")


def resolve_spenders(payload: Dict[str, Any], explicit_spenders: Iterable[str]) -> List[str]:
    spenders = [to_checksum_address(spender) for spender in explicit_spenders]
    if not spenders:
        spenders = [spender for spender, _allowance in extract_allowance_entries(payload)]
    return sorted(set(spenders))


def submit_approve(
    *,
    relayer: RelayerApiKeyClient,
    spender: str,
    amount_units: int,
    wait: bool,
) -> Dict[str, Any]:
    approve_data = encode_erc20_approve(spender, amount_units)
    submit_response = relayer.submit_transactions(
        [
            {
                "to": PUSD,
                "data": approve_data,
                "value": "0",
                "operation": 0,
                "type_code": 1,
            }
        ],
        metadata=f"approvePUSD:{spender}",
    )
    transaction_id = submit_response.get("transactionID") or submit_response.get("id")
    result: Dict[str, Any] = {"spender": spender, "submit": submit_response}
    if wait:
        if not transaction_id:
            raise RuntimeError(f"Relayer response missing transactionID: {submit_response}")
        result["final"] = relayer.poll_transaction(str(transaction_id))
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check and optionally approve pUSD allowance for Polymarket CLOB trading."
    )
    parser.add_argument(
        "--approve-pusd",
        type=str,
        default=None,
        metavar="AMOUNT",
        help="Set exact pUSD allowance to this amount for each collateral spender.",
    )
    parser.add_argument(
        "--spender",
        action="append",
        default=[],
        help="Approve a specific spender. Can be passed multiple times. Defaults to spenders from CLOB allowance response.",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Call update_balance_allowance even when not approving.",
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Do not poll relayer transactions before syncing. Use only if you will sync later.",
    )
    return parser


def main() -> None:
    load_dotenv()
    ca_bundle = configure_tls()
    args = build_parser().parse_args()

    print(f"[tls] ca_bundle={ca_bundle}")
    clob = create_trading_clob_client()
    before = get_collateral_balance_allowance(clob)
    summarize_balance_allowance("before", before)

    approve_results: List[Dict[str, Any]] = []
    should_sync = bool(args.sync)

    if args.approve_pusd is not None:
        amount_units = amount_to_units(args.approve_pusd)
        spenders = resolve_spenders(before, args.spender)
        if not spenders:
            raise SystemExit(
                "No collateral spenders found in CLOB response. Re-run with --spender 0x..."
            )

        relayer = RelayerApiKeyClient.from_env()
        print(
            "\n[approve]\n"
            f"wallet={relayer.wallet_address}\n"
            f"pUSD={PUSD}\n"
            f"target={args.approve_pusd} pUSD ({amount_units} base units)\n"
            f"spenders={', '.join(spenders)}"
        )
        for spender in spenders:
            approve_results.append(
                submit_approve(
                    relayer=relayer,
                    spender=spender,
                    amount_units=amount_units,
                    wait=not args.no_wait,
                )
            )
        print(json.dumps(approve_results, indent=2, ensure_ascii=False))
        should_sync = not args.no_wait

    if should_sync:
        print("\n[sync]")
        sync_response = update_collateral_balance_allowance(clob)
        print(json.dumps(sync_response, indent=2, ensure_ascii=False))

    after = get_collateral_balance_allowance(clob)
    summarize_balance_allowance("after", after)


if __name__ == "__main__":
    main()
