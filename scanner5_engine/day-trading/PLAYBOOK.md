# Scanner 5.0 Day Trading Playbook

Use this checklist with the `day-trading` skill. A blank or unverified item
means the trade is not ready.

## Pre-market checklist

- [ ] Confirm exchange, trading date, session and holiday/early-close status.
- [ ] Confirm paper/live account mode and connected broker.
- [ ] Confirm capital allocated, maximum loss per trade and daily loss limit.
- [ ] Check scheduled earnings, macro events, company announcements and halts.
- [ ] Run the correct exchange scanner and record its data timestamp.
- [ ] Reject partial, stale or incomplete scanner results as trade triggers.
- [ ] Select candidates only after reviewing liquidity and spread.

## Trade proposal checklist

- [ ] Completed candle confirms the setup.
- [ ] Entry level and invalidation level are explicit.
- [ ] Stop and target are set before sizing.
- [ ] Historical replay/backtest limitations are disclosed.
- [ ] Quantity is calculated from risk, not from desired profit.
- [ ] Maximum loss, order value, charges and slippage are estimated.
- [ ] Existing positions and total open risk are checked.
- [ ] All user-configured risk limits pass.
- [ ] Final order ticket is reviewed by the user.
- [ ] Explicit user confirmation is received before any live order.

## While a position is open

- [ ] Monitor only the agreed stop, target and time-based exit conditions.
- [ ] Never widen the stop to avoid taking a planned loss.
- [ ] Confirm actual broker fills; do not assume an alert means a fill.
- [ ] Recalculate remaining daily risk after every fill or exit.
- [ ] Stop taking new trades when the daily loss or trade-count limit is hit.

## End-of-day review

- [ ] Reconcile positions and actual fills with the broker.
- [ ] Close or explicitly document any permitted overnight position.
- [ ] Record realized result, charges and slippage from broker statements.
- [ ] Review rule violations and execution quality.
- [ ] Save lessons without changing the strategy based on one trade alone.
