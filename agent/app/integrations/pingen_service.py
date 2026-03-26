"""Pingen Briefversand integration (placeholder).

Pingen (https://pingen.com) provides an API for sending physical letters.
This module defines the interface; actual API calls will be implemented
once production credentials are available.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class PingenDeliverySpeed(str, Enum):
    PRIORITY = 'priority'
    ECONOMY = 'economy'


class PingenPrintColor(str, Enum):
    COLOR = 'color'
    GRAYSCALE = 'grayscale'


@dataclass
class PingenLetterResult:
    """Result of a Pingen send operation."""
    letter_id: str
    status: str
    tracking_url: str | None = None


class PingenService:
    """Placeholder for Pingen letter-sending integration.

    Configure via environment variables:
        PINGEN_CLIENT_ID     - OAuth2 client ID
        PINGEN_CLIENT_SECRET - OAuth2 client secret
        PINGEN_USE_STAGING   - Use staging API (default: true)
    """

    STAGING_URL = 'https://api-staging.pingen.com/v2'
    PRODUCTION_URL = 'https://api.pingen.com/v2'

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        use_staging: bool = True,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._base_url = self.STAGING_URL if use_staging else self.PRODUCTION_URL
        self._configured = bool(client_id and client_secret)

    @property
    def is_configured(self) -> bool:
        """Return True if Pingen credentials are set."""
        return self._configured

    async def send_letter(
        self,
        pdf_bytes: bytes,
        recipient_name: str,
        recipient_street: str,
        recipient_zip: str,
        recipient_city: str,
        recipient_country: str = 'CH',
        speed: PingenDeliverySpeed = PingenDeliverySpeed.ECONOMY,
        color: PingenPrintColor = PingenPrintColor.GRAYSCALE,
    ) -> PingenLetterResult:
        """Send a PDF letter via Pingen.

        This is a placeholder that logs the intent but does not
        call the Pingen API yet.

        Args:
            pdf_bytes: Raw PDF content to send.
            recipient_name: Full name of the recipient.
            recipient_street: Street address.
            recipient_zip: Postal code.
            recipient_city: City name.
            recipient_country: ISO country code (default CH).
            speed: Delivery speed (priority or economy).
            color: Print mode (color or grayscale).

        Returns:
            PingenLetterResult with a placeholder status.

        Raises:
            RuntimeError: If Pingen is not configured.
        """
        if not self._configured:
            logger.warning(
                'Pingen not configured -- letter to %s not sent '
                '(set PINGEN_CLIENT_ID and PINGEN_CLIENT_SECRET)',
                recipient_name,
            )
            return PingenLetterResult(
                letter_id='not-configured',
                status='SKIPPED',
            )

        # TODO: implement actual Pingen API calls:
        # 1. POST /oauth/token  -> obtain access token
        # 2. POST /organisations/{org}/letters/upload  -> upload PDF
        # 3. PATCH /organisations/{org}/letters/{id}/send  -> trigger send
        logger.info(
            'Pingen send_letter placeholder: %s, %s %s %s, speed=%s, color=%s, pdf_size=%d',
            recipient_name, recipient_street, recipient_zip,
            recipient_city, speed.value, color.value, len(pdf_bytes),
        )
        return PingenLetterResult(
            letter_id='placeholder',
            status='PENDING_IMPLEMENTATION',
        )

    async def get_letter_status(self, letter_id: str) -> dict:
        """Check the delivery status of a letter.

        Placeholder -- returns a static response.
        """
        logger.info('Pingen get_letter_status placeholder: %s', letter_id)
        return {
            'letter_id': letter_id,
            'status': 'PENDING_IMPLEMENTATION',
            'events': [],
        }
