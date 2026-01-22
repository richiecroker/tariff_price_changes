SELECT
  date,
  bnf_code,
  nm,
  vmpp,
  tariff_category,
  price_pence,
  prev_price AS previous_price_pence,
  prev_date AS previous_date,
  prev_tariff_category
FROM (
  SELECT
    date,
    bnf_code,
    nm,
    vmpp,
    dtcat.descr AS tariff_category,
    price_pence,
    LAG(price_pence) OVER (PARTITION BY vmpp ORDER BY date) AS prev_price,
    LAG(date) OVER (PARTITION BY vmpp ORDER BY date) AS prev_date,
    LAG(dtcat.descr) OVER (PARTITION BY vmpp ORDER BY date) AS prev_tariff_category
  FROM dmd.tariffprice AS tariff
  INNER JOIN dmd.vmpp_full AS vmpp_full
    ON vmpp_full.id = tariff.vmpp
  INNER JOIN dmd.dtpaymentcategory AS dtcat
    ON tariff.tariff_category = dtcat.cd
)
WHERE date = (SELECT MAX(date) FROM dmd.tariffprice)
ORDER BY vmpp, tariff_category