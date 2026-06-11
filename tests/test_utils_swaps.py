"""Tests for shared atomic swap request builders."""

from __future__ import annotations

from kaleido_cli.utils.swaps import confirm_swap_request, swap_request_from_quote

from .test_cmd_swap import _quote


def test_swap_request_from_quote():
    request = swap_request_from_quote(_quote())

    assert request.rfq_id == "rfq-1"
    assert request.from_asset == "BTC"
    assert request.from_amount == 100000
    assert request.to_asset == "rgb:usdt"
    assert request.to_amount == 500


def test_confirm_swap_request():
    request = confirm_swap_request(
        swapstring="swapstring",
        taker_pubkey="03abc",
        payment_hash="hash-1",
    )

    assert request.swapstring == "swapstring"
    assert request.taker_pubkey == "03abc"
    assert request.payment_hash == "hash-1"
