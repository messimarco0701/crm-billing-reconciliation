-- Staging: bring both sources to a common, comparable shape.
-- Everything is read as text first so that VAT numbers keep their leading zeros.

-- Company names are written in many ways ("Rossi Srl", "ROSSI S.R.L.", "rossi  srl").
-- This key strips accents, punctuation, spacing and the legal form so they all collapse to "ROSSI".
CREATE OR REPLACE MACRO name_key(n) AS
    trim(regexp_replace(
        regexp_replace(
            regexp_replace(strip_accents(upper(n)), '[^A-Z0-9 ]', '', 'g'),
        '\s+', ' ', 'g'),
    '\s(SRLS|SRL|SPA|SNC|SAS)\s*$', ''));

-- Italian VAT numbers have 11 digits. Anything else ("IT 0123...", spaces) is cleaned,
-- and whatever still is not 11 digits is treated as missing.
CREATE OR REPLACE MACRO vat_key(v) AS
    CASE WHEN length(regexp_replace(coalesce(v, ''), '[^0-9]', '', 'g')) = 11
         THEN regexp_replace(v, '[^0-9]', '', 'g') END;

CREATE OR REPLACE TABLE stg_deals AS
SELECT
    deal_id,
    deal_name,
    company_name,
    name_key(company_name)          AS name_key,
    vat_key(vat_number)             AS vat,
    channel,
    nullif(partner_name, '')        AS partner_name,
    stage,
    CAST(amount AS DECIMAL(12, 2))  AS amount,
    CAST(close_date AS DATE)        AS close_date,
    owner
FROM read_csv('{data_dir}/crm_deals.csv', all_varchar = true);

CREATE OR REPLACE TABLE stg_contracts AS
SELECT
    contract_id,
    customer_name,
    name_key(customer_name)             AS name_key,
    vat_key(vat_number)                 AS vat,
    product,
    CAST(start_date AS DATE)            AS start_date,
    CAST(end_date AS DATE)              AS end_date,
    CAST(annual_fee AS DECIMAL(12, 2))  AS annual_fee,
    status
FROM read_csv('{data_dir}/billing_contracts.csv', all_varchar = true);

CREATE OR REPLACE TABLE stg_plan AS
SELECT
    plan_line_id,
    contract_id,
    CAST(due_date AS DATE)          AS due_date,
    CAST(amount AS DECIMAL(12, 2))  AS amount
FROM read_csv('{data_dir}/billing_plan_lines.csv', all_varchar = true);
