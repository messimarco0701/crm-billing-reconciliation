-- First matching pass: the VAT number is the most reliable shared key.
-- Deals that have no usable VAT are handled afterwards in Python with fuzzy name matching,
-- and their results are appended to this same table.

CREATE OR REPLACE TABLE matches AS
SELECT
    d.deal_id,
    c.contract_id,
    'vat'               AS match_method,
    100.0               AS match_score
FROM stg_deals d
JOIN stg_contracts c ON d.vat = c.vat;
