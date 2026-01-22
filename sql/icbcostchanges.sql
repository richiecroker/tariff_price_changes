WITH price_changes AS (
  SELECT
    date,
    vmpp,
    tariff_category,
    price_pence,
    prev_price AS previous_price_pence,
    prev_date AS previous_date,
    prev_tariff_category
  FROM (
    SELECT
      date,
      vmpp,
      tariff_category,
      price_pence,
      LAG(price_pence) OVER (PARTITION BY vmpp ORDER BY date) AS prev_price,
      LAG(date) OVER (PARTITION BY vmpp ORDER BY date) AS prev_date,
      LAG(tariff_category) OVER (PARTITION BY vmpp ORDER BY date) AS prev_tariff_category
    FROM dmd.tariffprice
  )
  WHERE price_pence IS DISTINCT FROM prev_price
    AND date = (SELECT MAX(date) FROM dmd.tariffprice)
  ORDER BY vmpp, tariff_category
),

agg_price_changes AS (
  SELECT
    pc.date,
    pc.vmpp,
    vf.bnf_code,
    pc.tariff_category,
    pc.price_pence,
    pc.prev_tariff_category,
    pc.previous_price_pence,
    vf.nm,
    (pc.price_pence - pc.previous_price_pence) / (vf.qtyval * 100) AS price_diff_pu
  FROM price_changes pc
  INNER JOIN dmd.vmpp_full vf
    ON vf.id = pc.vmpp
),

bnf_code_price_changes AS (
  SELECT
    *,
    CASE WHEN ROW_NUMBER() OVER (PARTITION BY bnf_code ORDER BY price_diff_pu DESC) = 1
      THEN 1 ELSE 0
    END AS is_max_price_diff_pu
  FROM agg_price_changes
)

SELECT
  icb.name,
  rx.bnf_name,
  rx.bnf_code,
  SUM(quantity * bnf.price_diff_pu * is_max_price_diff_pu) AS price_difference
FROM hscic.normalised_prescribing AS rx
INNER JOIN hscic.ccgs AS ccgs
  ON rx.pct = ccgs.code
INNER JOIN hscic.stps AS icb
  ON ccgs.stp_id = icb.code
INNER JOIN bnf_code_price_changes AS bnf
  ON bnf.bnf_code = rx.bnf_code
WHERE month = (SELECT MAX(month) FROM hscic.normalised_prescribing)
  AND ccgs.org_type = 'CCG'
  AND ccgs.close_date IS NULL
GROUP BY icb.name, rx.bnf_name, rx.bnf_code