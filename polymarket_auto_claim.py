from __future__ import annotations

import argparse
import csv
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv
from eth_abi import encode
from eth_abi.packed import encode_packed
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import keccak, to_bytes, to_checksum_address
from hexbytes import HexBytes
from py_clob_client_v2.client import ClobClient  # type: ignore

load_dotenv()

CLOB_HOST = (
    os.getenv("CLOB_HOST", "https://clob-v2.polymarket.com").strip()
    or "https://clob-v2.polymarket.com"
)
HOST = CLOB_HOST
RELAYER_URL_DEFAULT = "https://relayer-v2.polymarket.com"
GAMMA_API_BASE = "https://gamma-api.polymarket.com"
CHAIN_ID_POLYGON = 137

PROXY_FACTORY = to_checksum_address("0xaB45c5A4B0c941a2F231C04C3f49182e1A254052")
RELAY_HUB = to_checksum_address("0xD216153c06E857cD7f72665E0aF1d7D82172F494")
CTF_CONTRACT = to_checksum_address("0x4D97DCd97eC945f40cF65F87097ACe5EA0476045")
USDC_E = to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")
PUSD = to_checksum_address("0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB")
COLLATERAL_ONRAMP = to_checksum_address("0x93070a847efEf7F70739046A929D47a521F5B8ee")
CTF_COLLATERAL_ADAPTER = to_checksum_address("0xAdA100Db00Ca00073811820692005400218FcE1f")
NEG_RISK_CTF_COLLATERAL_ADAPTER = to_checksum_address("0xadA2005600Dec949baf300f4C6120000bDB6eAab")
ZERO_BYTES32 = "0x" + ("00" * 32)

PROXY_INIT_CODE_HASH = "0xd21df8dc65880a8606f09fe0ce3df9b8869287ab0b058be05aa9e8af6330a00b"
SAFE_FACTORY = to_checksum_address("0xaacFeEa03eb1561C4e67d661e40682Bd20E3541b")
SAFE_INIT_CODE_HASH = "0x2bce2127ff07fb632d16c8347c4ebf501f4841168bed00d9e6ef715ddb6fcecf"
SAFE_DOMAIN_TYPEHASH = HexBytes("0x47e79534a245952e8b16893a336b85a3d9ea9fa8c573f3d803afb92a79469218")
SAFE_TX_TYPEHASH = HexBytes("0xbb8310d486368db6bd6f849402fdd73ad53d316b5a4b2644ad6efe0f941286d8")
ZERO_ADDRESS = to_checksum_address("0x0000000000000000000000000000000000000000")

# More precise relayer state handling.
TX_IN_FLIGHT_STATES = {"STATE_NEW", "STATE_EXECUTED"}
TX_FINAL_SUCCESS_STATES = {"STATE_MINED", "STATE_CONFIRMED"}
TX_TERMINAL_FAILURE_STATES = {"STATE_FAILED", "STATE_INVALID"}
TX_ALL_KNOWN_STATES = TX_IN_FLIGHT_STATES | TX_FINAL_SUCCESS_STATES | TX_TERMINAL_FAILURE_STATES
CLAIM_STATE_VERSION = 2


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_hex_prefix(value: str) -> str:
    return value if value.startswith("0x") else f"0x{value}"


def hex_to_bytes32(value: str) -> str:
    value = ensure_hex_prefix(value).lower()
    if len(value) != 66:
        raise ValueError(f"conditionId must be 32 bytes hex, got: {value}")
    return value


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def first_dict(obj: Any) -> Dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        return obj[0]
    return {}


def create_public_clob_client() -> Any:
    return ClobClient(host=CLOB_HOST, chain_id=CHAIN_ID_POLYGON)


def resolve_claim_collateral_token(value: Optional[str] = None) -> str:
    raw_value = (value or os.getenv("CLAIM_COLLATERAL_TOKEN", "pusd")).strip()
    if not raw_value:
        return USDC_E

    aliases = {
        "pusd": PUSD,
        "usdc.e": USDC_E,
        "usdce": USDC_E,
        "usdc_e": USDC_E,
    }
    resolved = aliases.get(raw_value.lower(), raw_value)
    return to_checksum_address(resolved)


def resolve_claim_redeem_target(value: Optional[str] = None) -> str:
    raw_value = (
        value or os.getenv("CLAIM_REDEEM_TARGET", "ctf_collateral_adapter")
    ).strip()
    if not raw_value:
        return CTF_CONTRACT

    aliases = {
        "ctf": CTF_CONTRACT,
        "ctf_collateral_adapter": CTF_COLLATERAL_ADAPTER,
        "neg_risk_ctf_collateral_adapter": NEG_RISK_CTF_COLLATERAL_ADAPTER,
    }
    resolved = aliases.get(raw_value.lower(), raw_value)
    return to_checksum_address(resolved)


def _get_create2_address(*, bytecode_hash: str, from_address: str, salt: bytes) -> str:
    bytecode_hash_bytes = to_bytes(hexstr=bytecode_hash)
    from_address_bytes = to_bytes(hexstr=from_address)
    address_hash = keccak(b"\xff" + from_address_bytes + salt + bytecode_hash_bytes)
    return to_checksum_address(address_hash[-20:])


def derive_proxy_wallet(owner_address: str, proxy_factory: str = PROXY_FACTORY) -> str:
    owner_address = to_checksum_address(owner_address)
    proxy_factory = to_checksum_address(proxy_factory)
    salt = keccak(encode_packed(["address"], [owner_address]))
    return _get_create2_address(
        bytecode_hash=PROXY_INIT_CODE_HASH,
        from_address=proxy_factory,
        salt=salt,
    )


def derive_safe_wallet(owner_address: str, safe_factory: str = SAFE_FACTORY) -> str:
    owner_address = to_checksum_address(owner_address)
    safe_factory = to_checksum_address(safe_factory)
    salt = keccak(encode(["address"], [owner_address]))
    return _get_create2_address(
        bytecode_hash=SAFE_INIT_CODE_HASH,
        from_address=safe_factory,
        salt=salt,
    )


def create_proxy_struct_hash(
    *,
    from_address: str,
    to: str,
    data: str,
    tx_fee: str,
    gas_price: str,
    gas_limit: str,
    nonce: str,
    relay_hub_address: str,
    relay_address: str,
) -> str:
    prefix = b"rlx:"
    message = (
        prefix
        + HexBytes(from_address)
        + HexBytes(to)
        + to_bytes(hexstr=ensure_hex_prefix(data))
        + int(tx_fee).to_bytes(32, "big")
        + int(gas_price).to_bytes(32, "big")
        + int(gas_limit).to_bytes(32, "big")
        + int(nonce).to_bytes(32, "big")
        + HexBytes(relay_hub_address)
        + HexBytes(relay_address)
    )
    return "0x" + keccak(message).hex()


def _safe_domain_separator(chain_id: int, safe_address: str) -> bytes:
    return keccak(
        encode(
            ["bytes32", "uint256", "address"],
            [SAFE_DOMAIN_TYPEHASH, int(chain_id), to_checksum_address(safe_address)],
        )
    )


def create_safe_struct_hash(
    *,
    chain_id: int,
    safe_address: str,
    to: str,
    value: str,
    data: str,
    operation: int,
    safe_tx_gas: str,
    base_gas: str,
    gas_price: str,
    gas_token: str,
    refund_receiver: str,
    nonce: str,
) -> str:
    safe_tx_hash = keccak(
        encode(
            [
                "bytes32",
                "address",
                "uint256",
                "bytes32",
                "uint8",
                "uint256",
                "uint256",
                "uint256",
                "address",
                "address",
                "uint256",
            ],
            [
                SAFE_TX_TYPEHASH,
                to_checksum_address(to),
                int(value),
                keccak(to_bytes(hexstr=ensure_hex_prefix(data))),
                int(operation),
                int(safe_tx_gas),
                int(base_gas),
                int(gas_price),
                to_checksum_address(gas_token),
                to_checksum_address(refund_receiver),
                int(nonce),
            ],
        )
    )
    domain_separator = _safe_domain_separator(chain_id, safe_address)
    return "0x" + keccak(b"\x19\x01" + domain_separator + safe_tx_hash).hex()


def sign_personal_hash(private_key: str, message_hash: str) -> str:
    account = Account.from_key(private_key)
    msg = encode_defunct(HexBytes(message_hash))
    return ensure_hex_prefix(account.sign_message(msg).signature.hex())


def split_and_pack_safe_signature(sig_hex: str) -> str:
    sig = HexBytes(sig_hex)
    if len(sig) != 65:
        raise ValueError(f"Invalid signature length: expected 65 bytes, got {len(sig)}")
    r = int.from_bytes(sig[0:32], "big")
    s = int.from_bytes(sig[32:64], "big")
    v_raw = sig[64]
    if v_raw in (0, 1):
        v = v_raw + 31
    elif v_raw in (27, 28):
        v = v_raw + 4
    else:
        raise ValueError("Invalid signature v for Safe signature packing")
    packed = encode_packed(["uint256", "uint256", "uint8"], [r, s, v])
    return "0x" + packed.hex()


def encode_proxy_transaction_data(transactions: List[Dict[str, str]]) -> str:
    selector = keccak(b"proxy((uint8,address,uint256,bytes)[])")[:4]
    tuples = []
    for txn in transactions:
        tuples.append(
            (
                int(txn.get("type_code", 1)),
                to_checksum_address(txn["to"]),
                int(txn.get("value", "0")),
                to_bytes(hexstr=ensure_hex_prefix(txn["data"])),
            )
        )
    encoded = encode(["(uint8,address,uint256,bytes)[]"], [tuples])
    return "0x" + (selector + encoded).hex()


def encode_redeem_positions_call(
    condition_id: str,
    *,
    collateral_token: Optional[str] = None,
    parent_collection_id: str = ZERO_BYTES32,
    index_sets: Optional[List[int]] = None,
) -> str:
    index_sets = index_sets or [1, 2]
    condition_id = hex_to_bytes32(condition_id)
    selector = keccak(b"redeemPositions(address,bytes32,bytes32,uint256[])")[:4]
    encoded_args = encode(
        ["address", "bytes32", "bytes32", "uint256[]"],
        [
            resolve_claim_collateral_token(collateral_token),
            HexBytes(parent_collection_id),
            HexBytes(condition_id),
            index_sets,
        ],
    )
    return "0x" + (selector + encoded_args).hex()


@dataclass
class RelayerConfig:
    relayer_url: str
    relayer_api_key: str
    relayer_api_key_address: str
    private_key: str
    chain_id: int = CHAIN_ID_POLYGON
    funder_address: Optional[str] = None
    relayer_tx_type: Optional[str] = None
    poly_signature_type: Optional[int] = None
    gas_limit: int = 500000
    poll_interval_seconds: float = 2.0
    poll_timeout_seconds: float = 120.0


class RelayerApiKeyClient:
    def __init__(self, config: RelayerConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update(
            {
                "RELAYER_API_KEY": config.relayer_api_key,
                "RELAYER_API_KEY_ADDRESS": config.relayer_api_key_address,
                "Content-Type": "application/json",
                "User-Agent": "polymarket-auto-claim/1.2",
            }
        )
        self.account = Account.from_key(config.private_key)
        self.signer_address = to_checksum_address(self.account.address)
        self.relayer_api_key_address = to_checksum_address(config.relayer_api_key_address)
        self.derived_safe_wallet = derive_safe_wallet(self.signer_address, SAFE_FACTORY)
        self.derived_proxy_wallet = derive_proxy_wallet(self.signer_address, PROXY_FACTORY)

        provided_funder = to_checksum_address(config.funder_address) if config.funder_address else None
        self.funder_address = provided_funder
        explicit_tx_type = (config.relayer_tx_type or "").strip().upper() or None
        inferred_tx_type: Optional[str] = None

        if explicit_tx_type:
            if explicit_tx_type not in {"SAFE", "PROXY"}:
                raise ValueError("CLAIM_RELAYER_TX_TYPE must be SAFE or PROXY")
            inferred_tx_type = explicit_tx_type
        elif provided_funder:
            if provided_funder == self.derived_safe_wallet:
                inferred_tx_type = "SAFE"
            elif provided_funder == self.derived_proxy_wallet:
                inferred_tx_type = "PROXY"
            else:
                raise ValueError(
                    "Configured FUNDER_ADDRESS does not match either wallet derived from PRIVATE_KEY. "
                    f"derived_safe={self.derived_safe_wallet}, derived_proxy={self.derived_proxy_wallet}, provided={provided_funder}"
                )
        elif config.poly_signature_type is not None:
            if int(config.poly_signature_type) == 2:
                inferred_tx_type = "SAFE"
            elif int(config.poly_signature_type) == 1:
                inferred_tx_type = "PROXY"
            else:
                raise ValueError(
                    "POLY_SIGNATURE_TYPE=0 (EOA) is not supported by this claim module. "
                    "Use signature type 1 or 2, or set CLAIM_RELAYER_TX_TYPE explicitly."
                )
        else:
            inferred_tx_type = "SAFE"

        self.relayer_tx_type = inferred_tx_type
        self.wallet_address = self.derived_safe_wallet if self.relayer_tx_type == "SAFE" else self.derived_proxy_wallet

        if provided_funder and provided_funder != self.wallet_address:
            raise ValueError(
                f"Configured FUNDER_ADDRESS does not match selected relayer wallet type {self.relayer_tx_type}. "
                f"expected={self.wallet_address}, provided={provided_funder}"
            )
        if self.relayer_api_key_address != self.signer_address:
            raise ValueError(
                "RELAYER_API_KEY_ADDRESS must match the signer derived from PRIVATE_KEY. "
                f"signer={self.signer_address}, relayer_api_key_address={self.relayer_api_key_address}"
            )

    def identity_payload(self) -> Dict[str, Any]:
        return {
            "signer_address": self.signer_address,
            "relayer_api_key_address": self.relayer_api_key_address,
            "relayer_tx_type": self.relayer_tx_type,
            "selected_wallet_address": self.wallet_address,
            "derived_safe_wallet": self.derived_safe_wallet,
            "derived_proxy_wallet": self.derived_proxy_wallet,
            "funder_address": self.funder_address or "",
            "chain_id": self.config.chain_id,
        }

    def assert_transaction_identity(self, txn: Dict[str, Any]) -> None:
        if not isinstance(txn, dict) or not txn:
            return
        txn_type = str(txn.get("type") or "").upper()
        txn_from = txn.get("from")
        proxy_wallet = txn.get("proxyWallet")
        if txn_type and txn_type != self.relayer_tx_type:
            raise RuntimeError(
                f"Relayer transaction type mismatch: expected={self.relayer_tx_type}, actual={txn_type}, txn={txn}"
            )
        if txn_from and to_checksum_address(str(txn_from)) != self.signer_address:
            raise RuntimeError(
                f"Relayer transaction signer mismatch: expected={self.signer_address}, actual={txn_from}, txn={txn}"
            )
        if proxy_wallet and to_checksum_address(str(proxy_wallet)) != self.wallet_address:
            raise RuntimeError(
                f"Relayer proxy wallet mismatch: expected={self.wallet_address}, actual={proxy_wallet}, txn={txn}"
            )

    @classmethod
    def from_env(cls) -> "RelayerApiKeyClient":
        load_dotenv()
        relayer_url = os.getenv("RELAYER_URL", RELAYER_URL_DEFAULT).rstrip("/")
        relayer_api_key = os.getenv("RELAYER_API_KEY", "").strip()
        relayer_api_key_address = os.getenv("RELAYER_API_KEY_ADDRESS", "").strip()
        private_key = os.getenv("PRIVATE_KEY", "").strip()
        funder_address = os.getenv("FUNDER_ADDRESS", "").strip() or None
        relayer_tx_type = os.getenv("CLAIM_RELAYER_TX_TYPE", "").strip() or None
        poly_signature_type_raw = os.getenv("POLY_SIGNATURE_TYPE", "").strip()
        poly_signature_type = int(poly_signature_type_raw) if poly_signature_type_raw else None
        gas_limit = int(os.getenv("CLAIM_GAS_LIMIT", "500000"))
        poll_interval_seconds = float(os.getenv("CLAIM_POLL_INTERVAL_SECONDS", "2"))
        poll_timeout_seconds = float(os.getenv("CLAIM_POLL_TIMEOUT_SECONDS", "120"))

        missing = []
        if not relayer_api_key:
            missing.append("RELAYER_API_KEY")
        if not relayer_api_key_address:
            missing.append("RELAYER_API_KEY_ADDRESS")
        if not private_key:
            missing.append("PRIVATE_KEY")
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

        return cls(
            RelayerConfig(
                relayer_url=relayer_url,
                relayer_api_key=relayer_api_key,
                relayer_api_key_address=relayer_api_key_address,
                private_key=private_key,
                funder_address=funder_address,
                relayer_tx_type=relayer_tx_type,
                poly_signature_type=poly_signature_type,
                gas_limit=gas_limit,
                poll_interval_seconds=poll_interval_seconds,
                poll_timeout_seconds=poll_timeout_seconds,
            )
        )

    def _url(self, path: str) -> str:
        return f"{self.config.relayer_url}{path}"

    def get_nonce(self, tx_type: str) -> Dict[str, Any]:
        resp = self.session.get(self._url("/nonce"), params={"address": self.signer_address, "type": tx_type}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict) or data.get("nonce") is None:
            raise RuntimeError(f"Invalid nonce response: {data}")
        return data

    def get_relay_payload(self) -> Dict[str, Any]:
        resp = self.session.get(self._url("/relay-payload"), params={"address": self.signer_address, "type": "PROXY"}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict) or data.get("nonce") is None or data.get("address") is None:
            raise RuntimeError(f"Invalid relay payload response: {data}")
        return data

    def get_transaction(self, transaction_id: str) -> Dict[str, Any]:
        resp = self.session.get(self._url("/transaction"), params={"id": transaction_id}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return first_dict(data)
        return first_dict(data)

    def get_deployed(self, address: Optional[str] = None) -> bool:
        resp = self.session.get(self._url("/deployed"), params={"address": address or self.wallet_address}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return bool(first_dict(data).get("deployed"))

    def build_proxy_request(self, inner_transactions: List[Dict[str, str]], metadata: str = "") -> Dict[str, Any]:
        relay_payload = self.get_relay_payload()
        relay_address = to_checksum_address(relay_payload["address"])
        nonce = str(relay_payload["nonce"])
        proxy_data = encode_proxy_transaction_data(inner_transactions)
        gas_limit = str(self.config.gas_limit)

        struct_hash = create_proxy_struct_hash(
            from_address=self.signer_address,
            to=PROXY_FACTORY,
            data=proxy_data,
            tx_fee="0",
            gas_price="0",
            gas_limit=gas_limit,
            nonce=nonce,
            relay_hub_address=RELAY_HUB,
            relay_address=relay_address,
        )
        signature = sign_personal_hash(self.config.private_key, struct_hash)

        return {
            "type": "PROXY",
            "from": self.signer_address,
            "to": PROXY_FACTORY,
            "proxyWallet": self.wallet_address,
            "data": proxy_data,
            "nonce": nonce,
            "signature": signature,
            "signatureParams": {
                "gasPrice": "0",
                "gasLimit": gas_limit,
                "relayerFee": "0",
                "relayHub": RELAY_HUB,
                "relay": relay_address,
            },
            "metadata": metadata or "",
        }

    def build_safe_request(self, inner_transactions: List[Dict[str, str]], metadata: str = "") -> Dict[str, Any]:
        if len(inner_transactions) != 1:
            raise NotImplementedError("This module currently supports a single SAFE inner transaction only")
        txn = inner_transactions[0]
        nonce_payload = self.get_nonce("SAFE")
        nonce = str(nonce_payload["nonce"])
        safe_tx_gas = "0"
        base_gas = "0"
        gas_price = "0"
        gas_token = ZERO_ADDRESS
        refund_receiver = ZERO_ADDRESS
        operation = int(txn.get("operation", 0))

        struct_hash = create_safe_struct_hash(
            chain_id=self.config.chain_id,
            safe_address=self.wallet_address,
            to=txn["to"],
            value=txn.get("value", "0"),
            data=txn["data"],
            operation=operation,
            safe_tx_gas=safe_tx_gas,
            base_gas=base_gas,
            gas_price=gas_price,
            gas_token=gas_token,
            refund_receiver=refund_receiver,
            nonce=nonce,
        )
        raw_signature = sign_personal_hash(self.config.private_key, struct_hash)
        packed_signature = split_and_pack_safe_signature(raw_signature)

        return {
            "type": "SAFE",
            "from": self.signer_address,
            "to": to_checksum_address(txn["to"]),
            "proxyWallet": self.wallet_address,
            "value": str(txn.get("value", "0")),
            "data": txn["data"],
            "nonce": nonce,
            "signature": packed_signature,
            "signatureParams": {
                "gasPrice": gas_price,
                "operation": str(operation),
                "safeTxnGas": safe_tx_gas,
                "baseGas": base_gas,
                "gasToken": gas_token,
                "refundReceiver": refund_receiver,
            },
            "metadata": metadata or "",
        }

    def submit_transactions(self, inner_transactions: List[Dict[str, str]], metadata: str = "") -> Dict[str, Any]:
        payload = self.build_safe_request(inner_transactions, metadata) if self.relayer_tx_type == "SAFE" else self.build_proxy_request(inner_transactions, metadata)
        resp = self.session.post(self._url("/submit"), data=json.dumps(payload), timeout=30)
        try:
            data = resp.json()
        except Exception:
            data = {"status_code": resp.status_code, "text": resp.text}
        if resp.status_code >= 400:
            raise RuntimeError(f"Relayer submit failed: {data}")
        parsed = first_dict(data)
        self.assert_transaction_identity(parsed)
        return parsed

    def poll_transaction(self, transaction_id: str) -> Dict[str, Any]:
        deadline = time.time() + self.config.poll_timeout_seconds
        last_seen: Dict[str, Any] = {}
        while time.time() < deadline:
            txn = self.get_transaction(transaction_id)
            last_seen = txn or last_seen
            self.assert_transaction_identity(txn)
            state = str(txn.get("state") or "")
            if state in TX_FINAL_SUCCESS_STATES:
                return txn
            if state in TX_TERMINAL_FAILURE_STATES:
                raise RuntimeError(f"Relayer transaction failed: {txn}")
            # STATE_NEW / STATE_EXECUTED stay in-flight and continue polling until timeout.
            time.sleep(self.config.poll_interval_seconds)
        return last_seen

    def redeem_positions(
        self,
        *,
        condition_id: str,
        metadata: str = "redeemPositions",
        index_sets: Optional[List[int]] = None,
        collateral_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        redeem_data = encode_redeem_positions_call(
            condition_id,
            collateral_token=collateral_token,
            index_sets=index_sets or [1, 2],
        )
        submit_response = self.submit_transactions(
            [
                {
                    "to": resolve_claim_redeem_target(),
                    "data": redeem_data,
                    "value": "0",
                    "operation": 0,
                    "type_code": 1,
                }
            ],
            metadata=metadata,
        )
        transaction_id = submit_response.get("transactionID") or submit_response.get("id")
        if not transaction_id:
            raise RuntimeError(f"Relayer response missing transactionID: {submit_response}")
        final_txn = self.poll_transaction(str(transaction_id))
        return {"submit": submit_response, "final": final_txn}


class MarketResolver:
    def __init__(self, timeout: float = 15.0):
        self.session = requests.Session()
        self.timeout = timeout
        self.clob = create_public_clob_client()

    def gamma_market_by_slug(self, slug: str) -> Dict[str, Any]:
        resp = self.session.get(f"{GAMMA_API_BASE}/markets/slug/{slug}", timeout=self.timeout)
        resp.raise_for_status()
        return first_dict(resp.json())

    def condition_id_from_slug(self, slug: str) -> Optional[str]:
        market = self.gamma_market_by_slug(slug)
        condition_id = market.get("conditionId")
        return str(condition_id) if condition_id else None

    def clob_market(self, condition_id: str) -> Dict[str, Any]:
        try:
            data = self.clob.get_market(condition_id)
            return first_dict(data)
        except Exception:
            return {}

    def winner_from_market_payload(self, payload: Dict[str, Any]) -> Optional[str]:
        tokens = payload.get("tokens")
        if isinstance(tokens, list):
            for token in tokens:
                if isinstance(token, dict) and token.get("winner"):
                    outcome = token.get("outcome") or token.get("name")
                    return str(outcome) if outcome else "WINNER_FOUND"
        return None

    def resolution_status(self, *, slug: Optional[str] = None, condition_id: Optional[str] = None) -> Dict[str, Any]:
        gamma_payload: Dict[str, Any] = {}
        if slug:
            try:
                gamma_payload = self.gamma_market_by_slug(slug)
            except Exception:
                gamma_payload = {}
            if not condition_id:
                cid = gamma_payload.get("conditionId")
                if cid:
                    condition_id = str(cid)

        clob_payload: Dict[str, Any] = {}
        if condition_id:
            clob_payload = self.clob_market(condition_id)

        gamma_winner = self.winner_from_market_payload(gamma_payload)
        clob_winner = self.winner_from_market_payload(clob_payload)

        resolved = False
        reason = "unknown"
        if clob_winner:
            resolved = True
            reason = "clob_winner"
        elif gamma_winner:
            resolved = True
            reason = "gamma_winner"
        elif clob_payload.get("closed") is True and gamma_payload.get("closed") is True:
            resolved = True
            reason = "closed_both_sources"

        return {
            "resolved": resolved,
            "reason": reason,
            "winner": clob_winner or gamma_winner,
            "condition_id": condition_id,
            "gamma": {
                "slug": gamma_payload.get("slug"),
                "closed": gamma_payload.get("closed"),
                "active": gamma_payload.get("active"),
                "acceptingOrders": gamma_payload.get("acceptingOrders"),
                "question": gamma_payload.get("question"),
            },
            "clob": {
                "closed": clob_payload.get("closed"),
                "question": clob_payload.get("question"),
            },
        }


def transaction_state_to_claim_status(state: Optional[str]) -> str:
    state = str(state or "")
    if state == "STATE_CONFIRMED":
        return "confirmed"
    if state == "STATE_MINED":
        return "mined"
    if state == "STATE_EXECUTED":
        return "executed"
    if state == "STATE_NEW":
        return "submitted"
    if state in TX_TERMINAL_FAILURE_STATES:
        return "failed"
    return "unknown"


def is_claim_final_success(status: Optional[str]) -> bool:
    return status in {"mined", "confirmed"}


class AutoClaimDaemon:
    def __init__(
        self,
        *,
        relayer_client: RelayerApiKeyClient,
        resolver: Optional[MarketResolver] = None,
        ledger_dir: Path = Path("ledger"),
        state_path: Optional[Path] = None,
        validate_state: bool = True,
    ):
        self.relayer = relayer_client
        self.resolver = resolver or MarketResolver()
        self.ledger_dir = ledger_dir
        self.orders_csv_path = ledger_dir / "orders.csv"
        self.market_state_json_path = ledger_dir / "market_state.json"
        self.state_path = state_path or Path(os.getenv("CLAIM_STATE_PATH", str(ledger_dir / "claim_state.json")))
        self.state_identity = self.relayer.identity_payload()
        self.state = self._load_state(validate_state=validate_state)

    @classmethod
    def from_env(cls, *, validate_state: bool = True) -> "AutoClaimDaemon":
        load_dotenv()
        relayer = RelayerApiKeyClient.from_env()
        ledger_dir = Path(os.getenv("LEDGER_DIR", "ledger"))
        return cls(relayer_client=relayer, ledger_dir=ledger_dir, validate_state=validate_state)

    def _default_state(self) -> Dict[str, Any]:
        return {
            "state_version": CLAIM_STATE_VERSION,
            "identity": dict(self.state_identity),
            "markets": {},
        }

    def _state_identity_mismatch(self, actual_identity: Any) -> List[str]:
        mismatches: List[str] = []
        if not isinstance(actual_identity, dict):
            return ["identity_missing"]
        for key, expected in self.state_identity.items():
            actual = actual_identity.get(key)
            if actual != expected:
                mismatches.append(f"{key}: expected={expected!r}, actual={actual!r}")
        return mismatches

    def _load_state(self, *, validate_state: bool) -> Dict[str, Any]:
        if not self.state_path.exists():
            state = self._default_state()
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            write_json(self.state_path, state)
            return state

        raw_state = read_json(self.state_path, None)
        if raw_state is None:
            raise ValueError(
                f"Claim state file is unreadable or invalid JSON: {self.state_path}. "
                "Delete the file and restart the claim watcher."
            )
        if not isinstance(raw_state, dict):
            raise ValueError(
                f"Claim state file has invalid root type at {self.state_path}. "
                "Delete the file and restart the claim watcher."
            )

        markets = raw_state.get("markets")
        if not isinstance(markets, dict):
            raise ValueError(
                f"Claim state file is in legacy format and is not supported: {self.state_path}. "
                "Delete the file and restart the claim watcher."
            )

        state_version = raw_state.get("state_version")
        identity = raw_state.get("identity")
        if state_version != CLAIM_STATE_VERSION or not isinstance(identity, dict):
            raise ValueError(
                f"Claim state file is missing account identity metadata: {self.state_path}. "
                "Delete the file and restart the claim watcher."
            )

        if validate_state:
            mismatches = self._state_identity_mismatch(identity)
            if mismatches:
                raise ValueError(
                    f"Claim state file belongs to a different account: {self.state_path}. "
                    + " | ".join(mismatches)
                    + " | Delete the file and restart the claim watcher."
                )

        raw_state["state_version"] = CLAIM_STATE_VERSION
        raw_state["identity"] = dict(identity)
        raw_state["markets"] = markets
        return raw_state

    def save_state(self) -> None:
        self.state["state_version"] = CLAIM_STATE_VERSION
        self.state["identity"] = dict(self.state_identity)
        self.state.setdefault("markets", {})
        write_json(self.state_path, self.state)

    def _market_key(self, slug: Optional[str], condition_id: Optional[str]) -> str:
        return slug or condition_id or "unknown"

    def register_market(self, *, slug: Optional[str], condition_id: Optional[str], question: Optional[str] = None) -> Dict[str, Any]:
        key = self._market_key(slug, condition_id)
        market = self.state["markets"].get(key, {})
        market.setdefault("created_at", utcnow_iso())
        if slug:
            market["slug"] = slug
        if condition_id:
            market["condition_id"] = condition_id
        if question:
            market["question"] = question
        market.setdefault("claim_status", "pending")
        market.setdefault("claim_attempts", 0)
        self.state["markets"][key] = market
        self.save_state()
        return market

    def load_candidate_markets_from_orders(self) -> List[Dict[str, Any]]:
        candidates: Dict[str, Dict[str, Any]] = {}
        if self.orders_csv_path.exists():
            with self.orders_csv_path.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    slug = (row.get("market_slug") or "").strip()
                    if not slug:
                        continue
                    candidate = candidates.setdefault(slug, {"slug": slug})
                    if row.get("market_question"):
                        candidate["question"] = row["market_question"]
        market_state = read_json(self.market_state_json_path, {})
        market_ledgers = market_state.get("market_ledgers", {}) if isinstance(market_state, dict) else {}
        if market_state and not isinstance(market_ledgers, dict):
            print("⚠️ market_state.json 缺少 market_ledgers，略過 state market sync")
            market_ledgers = {}

        for slug, payload in market_ledgers.items():
            if not isinstance(payload, dict):
                continue
            candidate = candidates.setdefault(slug, {"slug": slug})
            if payload.get("market_question"):
                candidate["question"] = payload["market_question"]
            if payload.get("condition_id"):
                candidate["condition_id"] = payload["condition_id"]
        return list(candidates.values())

    def sync_traded_markets_into_state(self) -> None:
        for market in self.load_candidate_markets_from_orders():
            slug = market.get("slug")
            condition_id = market.get("condition_id")
            if not condition_id and slug:
                try:
                    condition_id = self.resolver.condition_id_from_slug(slug)
                except Exception:
                    condition_id = None
            self.register_market(slug=slug, condition_id=condition_id, question=market.get("question"))

    def refresh_existing_transaction(self, market: Dict[str, Any]) -> Tuple[bool, Optional[Dict[str, Any]]]:
        txid = market.get("last_transaction_id")
        if not txid:
            return False, None
        try:
            txn = self.relayer.get_transaction(str(txid))
        except Exception as exc:
            market["last_error"] = f"refresh_existing_transaction failed: {exc}"
            self.save_state()
            return False, None

        state = str(txn.get("state") or "")
        market["last_transaction_state"] = state
        market["last_transaction_hash"] = txn.get("transactionHash") or market.get("last_transaction_hash")
        market["last_transaction_checked_at"] = utcnow_iso()
        mapped = transaction_state_to_claim_status(state)
        if mapped != "unknown":
            market["claim_status"] = mapped
            if mapped in {"mined", "confirmed"} and not market.get("claimed_at"):
                market["claimed_at"] = utcnow_iso()
        self.save_state()
        return True, txn

    def claim_market(
        self,
        *,
        slug: Optional[str] = None,
        condition_id: Optional[str] = None,
        question: Optional[str] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        status = self.resolver.resolution_status(slug=slug, condition_id=condition_id)
        condition_id = status.get("condition_id") or condition_id
        market = self.register_market(slug=slug, condition_id=condition_id, question=question)

        if is_claim_final_success(market.get("claim_status")) and not force:
            return {"ok": True, "skipped": True, "reason": "already_finalized", "market": market}

        # If a transaction is already in-flight, refresh it first instead of resubmitting.
        if market.get("last_transaction_id") and market.get("claim_status") in {"submitted", "executed", "unknown"} and not force:
            refreshed, txn = self.refresh_existing_transaction(market)
            if refreshed and txn:
                state = str(txn.get("state") or "")
                claim_status = transaction_state_to_claim_status(state)
                if is_claim_final_success(claim_status):
                    return {"ok": True, "skipped": True, "reason": f"existing_tx_{claim_status}", "market": market, "result": {"final": txn}}
                if claim_status in {"submitted", "executed"}:
                    return {"ok": True, "skipped": True, "reason": f"existing_tx_{claim_status}", "market": market, "result": {"final": txn}}
                if claim_status == "failed":
                    # fall through and allow a fresh submission.
                    pass

        if not condition_id:
            market["claim_status"] = "pending_missing_condition_id"
            market["last_error"] = "No condition_id available"
            self.save_state()
            return {"ok": False, "skipped": True, "reason": "missing_condition_id", "market": market}

        if not status.get("resolved") and not force:
            market["claim_status"] = "pending_resolution"
            market["resolution_status"] = status
            self.save_state()
            return {"ok": False, "skipped": True, "reason": "not_resolved_yet", "market": market}

        market["claim_status"] = "submitting"
        market["claim_attempts"] = int(market.get("claim_attempts", 0)) + 1
        market["last_submit_started_at"] = utcnow_iso()
        market["resolution_status"] = status
        self.save_state()

        metadata = f"redeemPositions:{slug or condition_id}"
        try:
            result = self.relayer.redeem_positions(condition_id=condition_id, metadata=metadata)
            submit = result.get("submit", {})
            final = result.get("final", {})
            final_state = str(final.get("state") or submit.get("state") or "")
            claim_status = transaction_state_to_claim_status(final_state)

            market["claim_status"] = claim_status
            market["last_transaction_id"] = submit.get("transactionID") or submit.get("id")
            market["last_transaction_hash"] = final.get("transactionHash") or submit.get("transactionHash")
            market["last_transaction_state"] = final_state
            market["last_error"] = ""
            if claim_status in {"mined", "confirmed"}:
                market["claimed_at"] = utcnow_iso()
            self.save_state()

            response = {"ok": True, "market": market, "result": result}
            if claim_status in {"submitted", "executed", "unknown"}:
                response["pending"] = True
                response["reason"] = f"tx_{claim_status}"
            return response
        except Exception as exc:
            market["claim_status"] = "failed"
            market["last_failed_at"] = utcnow_iso()
            market["last_error"] = str(exc)
            self.save_state()
            return {"ok": False, "market": market, "error": str(exc)}

    def run_once(self, force: bool = False) -> List[Dict[str, Any]]:
        self.sync_traded_markets_into_state()
        results: List[Dict[str, Any]] = []
        for market in list(self.state["markets"].values()):
            if not isinstance(market, dict):
                continue
            if is_claim_final_success(market.get("claim_status")) and not force:
                continue
            results.append(
                self.claim_market(
                    slug=market.get("slug"),
                    condition_id=market.get("condition_id"),
                    question=market.get("question"),
                    force=force,
                )
            )
        return results

    def run_forever(self, interval_seconds: float = 20.0, force: bool = False) -> None:
        while True:
            results = self.run_once(force=force)
            printable = {
                "ts": utcnow_iso(),
                "checked": len(results),
                "finalized": sum(1 for r in results if is_claim_final_success((r.get("market") or {}).get("claim_status"))),
                "in_flight": sum(1 for r in results if ((r.get("market") or {}).get("claim_status") in {"submitted", "executed"})),
                "pending_or_skipped": sum(1 for r in results if r.get("skipped") is True),
                "failed": sum(1 for r in results if r.get("ok") is False and not r.get("skipped")),
            }
            print(json.dumps(printable, ensure_ascii=False))
            time.sleep(interval_seconds)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Polymarket auto-claim daemon using Relayer API Key")
    sub = parser.add_subparsers(dest="command", required=True)

    watch = sub.add_parser("watch", help="Scan ledger and auto-claim resolved markets forever")
    watch.add_argument("--interval", type=float, default=float(os.getenv("CLAIM_SCAN_INTERVAL_SECONDS", "20")))
    watch.add_argument("--force", action="store_true")

    run_once = sub.add_parser("run-once", help="Scan ledger once and attempt claims")
    run_once.add_argument("--force", action="store_true")

    claim = sub.add_parser("claim", help="Claim a single market by condition_id or slug")
    claim.add_argument("--condition-id", type=str, default=None)
    claim.add_argument("--slug", type=str, default=None)
    claim.add_argument("--question", type=str, default=None)
    claim.add_argument("--force", action="store_true")

    info = sub.add_parser("info", help="Show signer/wallet/relayer deployment info")
    return parser


def main() -> None:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "info":
        relayer = RelayerApiKeyClient.from_env()
        ledger_dir = Path(os.getenv("LEDGER_DIR", "ledger"))
        state_path = Path(os.getenv("CLAIM_STATE_PATH", str(ledger_dir / "claim_state.json")))
        payload = {
            "clob_host": CLOB_HOST,
            "signer_address": relayer.signer_address,
            "relayer_api_key_address": relayer.relayer_api_key_address,
            "relayer_tx_type": relayer.relayer_tx_type,
            "claim_collateral_token": resolve_claim_collateral_token(),
            "claim_redeem_target": resolve_claim_redeem_target(),
            "derived_safe_wallet": relayer.derived_safe_wallet,
            "derived_proxy_wallet": relayer.derived_proxy_wallet,
            "selected_wallet_address": relayer.wallet_address,
            "selected_wallet_deployed": relayer.get_deployed(),
            "state_identity": relayer.identity_payload(),
            "state_path": str(state_path),
            "ledger_dir": str(ledger_dir),
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    daemon = AutoClaimDaemon.from_env()

    if args.command == "watch":
        daemon.run_forever(interval_seconds=args.interval, force=args.force)
        return

    if args.command == "run-once":
        print(json.dumps(daemon.run_once(force=args.force), indent=2, ensure_ascii=False))
        return

    if args.command == "claim":
        if not args.condition_id and not args.slug:
            raise SystemExit("claim requires --condition-id or --slug")
        result = daemon.claim_market(slug=args.slug, condition_id=args.condition_id, question=args.question, force=args.force)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return


if __name__ == "__main__":
    main()
