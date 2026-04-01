-- Migration: Populate frya_business_profile from frya_user_preferences
INSERT INTO frya_business_profile (user_id, tenant_id, company_name, company_street, company_zip, company_city, tax_number, company_iban, company_bic, is_kleinunternehmer, default_hourly_rate, invoice_template, company_logo_b64)
SELECT
    COALESCE(up.user_id, 'system'),
    up.tenant_id,
    MAX(CASE WHEN up.key = 'company_name' THEN up.value END),
    MAX(CASE WHEN up.key = 'company_street' THEN up.value END),
    MAX(CASE WHEN up.key = 'company_zip_city' THEN SPLIT_PART(up.value, ' ', 1) END),
    MAX(CASE WHEN up.key = 'company_zip_city' THEN SUBSTRING(up.value FROM POSITION(' ' IN up.value) + 1) END),
    MAX(CASE WHEN up.key = 'tax_number' AND up.value NOT LIKE 'DE%' THEN up.value END),
    MAX(CASE WHEN up.key = 'company_iban' THEN up.value END),
    MAX(CASE WHEN up.key = 'company_bic' THEN up.value END),
    COALESCE(MAX(CASE WHEN up.key = 'kleinunternehmer' THEN up.value END), 'false') = 'true',
    NULLIF(MAX(CASE WHEN up.key = 'default_hourly_rate' THEN up.value END), '')::DECIMAL(10,2),
    COALESCE(MAX(CASE WHEN up.key = 'invoice_template' THEN up.value END), 'clean'),
    MAX(CASE WHEN up.key = 'company_logo_b64' THEN up.value END)
FROM frya_user_preferences up
WHERE up.key IN ('company_name','company_street','company_zip_city','tax_number','company_iban','company_bic','kleinunternehmer','default_hourly_rate','invoice_template','company_logo_b64')
GROUP BY COALESCE(up.user_id, 'system'), up.tenant_id
ON CONFLICT (user_id, tenant_id) DO NOTHING;
