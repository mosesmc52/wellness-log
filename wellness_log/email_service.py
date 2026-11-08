"""Amazon SES email delivery."""

import os
from dataclasses import dataclass

from SES import AmazonSES


@dataclass(frozen=True)
class SESConfig:
    region: str
    from_address: str
    to_addresses: tuple[str, ...]
    access_key: str | None
    secret_key: str | None
    session_token: str | None

    @classmethod
    def from_env(cls) -> "SESConfig | None":
        from_address = os.getenv("FROM_ADDRESS", "").strip()
        to_addresses = tuple(
            address.strip()
            for address in os.getenv("TO_ADDRESSES", "").split(",")
            if address.strip()
        )
        if not from_address or not to_addresses:
            return None
        access_key = os.getenv("AWS_SES_ACCESS_KEY_ID") or None
        secret_key = os.getenv("AWS_SES_SECRET_ACCESS_KEY") or None
        if bool(access_key) != bool(secret_key):
            raise RuntimeError(
                "AWS_SES_ACCESS_KEY_ID and AWS_SES_SECRET_ACCESS_KEY must either both be set or both be omitted"
            )
        return cls(
            region=os.getenv("AWS_SES_REGION_NAME") or "us-east-1",
            from_address=from_address,
            to_addresses=to_addresses,
            access_key=access_key,
            secret_key=secret_key,
            session_token=os.getenv("AWS_SES_SESSION_TOKEN") or None,
        )


def send_report(subject: str, text_body: str, html_body: str) -> None:
    config = SESConfig.from_env()
    if config is None:
        raise RuntimeError(
            "FROM_ADDRESS and TO_ADDRESSES must be configured to send reports through SES"
        )
    client = AmazonSES(
        region=config.region,
        access_key=config.access_key,
        secret_key=config.secret_key,
        session_token=config.session_token,
        from_address=config.from_address,
    )
    client.send_email(config.to_addresses, subject, text_body, html_body)
