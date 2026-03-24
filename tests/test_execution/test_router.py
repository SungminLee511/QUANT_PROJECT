"""Tests for order state machine."""

import pytest

from execution.order import InvalidTransitionError, OrderState
from shared.enums import OrderStatus


class TestOrderStateMachine:
    def test_valid_transition_pending_to_placed(self):
        order = OrderState(order_id="test-1")
        order.transition(OrderStatus.PLACED)
        assert order.status == OrderStatus.PLACED

    def test_valid_transition_placed_to_filled(self):
        order = OrderState(order_id="test-1")
        order.transition(OrderStatus.PLACED)
        order.transition(OrderStatus.FILLED)
        assert order.status == OrderStatus.FILLED
        assert order.is_terminal

    def test_valid_transition_placed_to_partial_to_filled(self):
        order = OrderState(order_id="test-1")
        order.transition(OrderStatus.PLACED)
        order.transition(OrderStatus.PARTIAL)
        order.transition(OrderStatus.FILLED)
        assert order.status == OrderStatus.FILLED

    def test_invalid_transition_raises(self):
        order = OrderState(order_id="test-1")
        order.transition(OrderStatus.PLACED)
        order.transition(OrderStatus.FILLED)
        with pytest.raises(InvalidTransitionError):
            order.transition(OrderStatus.CANCELLED)

    def test_pending_to_rejected(self):
        order = OrderState(order_id="test-1")
        order.transition(OrderStatus.REJECTED)
        assert order.status == OrderStatus.REJECTED
        assert order.is_terminal

    def test_pending_cannot_go_to_filled(self):
        order = OrderState(order_id="test-1")
        with pytest.raises(InvalidTransitionError):
            order.transition(OrderStatus.FILLED)
