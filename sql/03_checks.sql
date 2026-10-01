-- Checks: each block below is one business rule.
-- Every row in the output is something a person should look at, with the amount
-- involved so the list can be sorted by what matters most.

CREATE OR REPLACE TABLE anomalies AS
WITH
won_deals AS (
    SELECT * FROM stg_deals WHERE stage = getvariable('won_stage')
),
paired AS (
    SELECT d.*, c.contract_id, c.vat AS contract_vat, c.annual_fee, c.status
    FROM matches m
    JOIN stg_deals d USING (deal_id)
    JOIN stg_contracts c USING (contract_id)
),
plan_totals AS (
    SELECT contract_id, count(*) AS n_lines, sum(amount) AS plan_total
    FROM stg_plan
    GROUP BY contract_id
)

-- The customer signed, but nobody is billing them
SELECT d.vat, 'missing_in_billing' AS anomaly_type, 'high' AS severity,
       d.deal_id, NULL AS contract_id,
       'Deal is Closed Won but no billing contract was found' AS detail,
       d.amount AS amount_at_stake
FROM won_deals d
WHERE d.deal_id NOT IN (SELECT deal_id FROM matches)

UNION ALL
-- We are billing someone the sales team never recorded
SELECT c.vat, 'missing_in_crm', 'high',
       NULL, c.contract_id,
       'Active contract with no matching deal in the CRM',
       c.annual_fee
FROM stg_contracts c
WHERE c.status = 'Active'
  AND c.contract_id NOT IN (SELECT contract_id FROM matches)

UNION ALL
-- Both systems know the customer, but disagree on how much they pay
SELECT p.contract_vat, 'amount_mismatch', 'medium',
       p.deal_id, p.contract_id,
       printf('CRM %.2f vs billing %.2f (%+.1f%%)',
              p.amount::DOUBLE, p.annual_fee::DOUBLE,
              100 * (p.amount - p.annual_fee)::DOUBLE / p.annual_fee::DOUBLE),
       abs(p.amount - p.annual_fee)
FROM paired p
WHERE abs(p.amount - p.annual_fee) > getvariable('amount_tolerance') * p.annual_fee

UNION ALL
-- Contract is live but the deal is still open in the CRM: pipeline is overstated
SELECT p.contract_vat, 'stage_mismatch', 'medium',
       p.deal_id, p.contract_id,
       'Contract is Active but deal stage is ' || p.stage,
       NULL
FROM paired p
WHERE p.status = 'Active' AND p.stage <> getvariable('won_stage')

UNION ALL
-- Active contract that will never generate an invoice
SELECT c.vat, 'no_billing_plan', 'high',
       NULL, c.contract_id,
       'Active contract with no billing plan lines',
       c.annual_fee
FROM stg_contracts c
LEFT JOIN plan_totals t USING (contract_id)
WHERE c.status = 'Active' AND t.contract_id IS NULL

UNION ALL
-- Billing plan exists but does not add up to the contract value
SELECT c.vat, 'plan_total_mismatch', 'medium',
       NULL, c.contract_id,
       printf('Plan total %.2f over %d lines vs annual fee %.2f',
              t.plan_total::DOUBLE, t.n_lines, c.annual_fee::DOUBLE),
       abs(c.annual_fee - t.plan_total)
FROM stg_contracts c
JOIN plan_totals t USING (contract_id)
WHERE abs(c.annual_fee - t.plan_total) > 0.01

UNION ALL
-- Commercial policy: nothing below the minimum fee
SELECT c.vat, 'below_minimum_fee', 'medium',
       NULL, c.contract_id,
       printf('Annual fee %.2f is below the minimum of %.2f',
              c.annual_fee::DOUBLE, getvariable('minimum_fee')::DOUBLE),
       getvariable('minimum_fee') - c.annual_fee
FROM stg_contracts c
WHERE c.annual_fee < getvariable('minimum_fee')

UNION ALL
-- Naming convention, so that reports grouping by deal name keep working
SELECT coalesce(d.vat, p.contract_vat), 'deal_name_format', 'low',
       d.deal_id, NULL,
       'Deal name "' || d.deal_name || '" does not follow COMPANY | PRODUCT | YEAR',
       NULL
FROM stg_deals d
LEFT JOIN paired p USING (deal_id)
WHERE NOT regexp_full_match(d.deal_name, getvariable('deal_name_pattern'))

UNION ALL
-- Same customer created twice: inflates pipeline and splits history
SELECT vat, 'duplicate_vat', 'medium',
       string_agg(deal_id, ', ' ORDER BY deal_id), NULL,
       printf('%d won deals share this VAT number: %s',
              count(*), string_agg(company_name, ' / ' ORDER BY deal_id)),
       NULL
FROM won_deals
WHERE vat IS NOT NULL
GROUP BY vat
HAVING count(*) > 1

UNION ALL
-- Not wrong yet, but it is how the next problem starts
SELECT p.contract_vat, 'missing_vat', 'low',
       d.deal_id, p.contract_id,
       printf('No VAT on the deal, matched by name with score %.0f', m.match_score),
       NULL
FROM stg_deals d
JOIN matches m USING (deal_id)
JOIN paired p USING (deal_id)
WHERE d.vat IS NULL;
