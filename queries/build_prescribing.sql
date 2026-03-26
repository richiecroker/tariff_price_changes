SELECT
  rx.practice,  
  rx.bnf_name,
  rx.bnf_code,
  SUM(rx.quantity) as quantity
FROM hscic.normalised_prescribing rx
INNER JOIN hscic.ccgs ccgs
  ON rx.pct = ccgs.code
INNER JOIN hscic.stps icb
  ON ccgs.stp_id = icb.code
WHERE month = (SELECT MAX(month) FROM hscic.normalised_prescribing)
  AND ccgs.org_type = 'CCG'
  AND ccgs.close_date IS NULL
GROUP BY rx.practice, rx.bnf_name, rx.bnf_code