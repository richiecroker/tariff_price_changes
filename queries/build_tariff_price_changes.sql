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
    DATE(pc.date) AS date,
    CAST(pc.vmpp AS STRING) AS vmpp,
    vf.bnf_code,
    pc.tariff_category,
    dtcat.descr AS tariff_cat,
    pc.price_pence,
    pc.prev_tariff_category,
    prev_dtcat.descr AS prev_tariff_cat,
    pc.previous_price_pence,
    vf.nm,
    (((1 - CASE
            WHEN pc.tariff_category IN (1, 11) THEN 0.2
            WHEN pc.tariff_category IN (5, 6, 7, 8, 10) THEN 0.0985
            ELSE 0.05
        END) * pc.price_pence) -
     ((1 - CASE
            WHEN pc.prev_tariff_category IN (1, 11) THEN 0.2
            WHEN pc.prev_tariff_category IN (5, 6, 7, 8, 10) THEN 0.0985
            ELSE 0.05
        END) * pc.previous_price_pence)) / (vf.qtyval * 100) AS price_diff_pu
  FROM price_changes pc
  INNER JOIN dmd.vmpp_full vf
    ON vf.id = pc.vmpp
  INNER JOIN dmd.dtpaymentcategory AS dtcat
    ON pc.tariff_category = dtcat.cd
  INNER JOIN dmd.dtpaymentcategory AS prev_dtcat
    ON pc.prev_tariff_category = prev_dtcat.cd
),

bnf_code_price_changes AS (
  SELECT
    *,
    CASE 
        WHEN ROW_NUMBER() OVER (PARTITION BY bnf_code ORDER BY ABS(price_diff_pu) DESC) = 1
        THEN 1 
        ELSE 0
    END AS is_max_price_diff_pu
  FROM agg_price_changes
)

SELECT * FROM bnf_code_price_changes