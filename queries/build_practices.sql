SELECT
    REPLACE(INITCAP(practice.name), 'Gp', 'GP') AS practice_name,
    practice.code AS practice_code,
    REPLACE(INITCAP(pcn.name), 'Pcn', 'PCN') AS pcn_name,
    pcn.code AS pcn_code,
    REPLACE(CONCAT(INITCAP(REPLACE(REPLACE(stp.name, ' INTEGRATED CARE BOARD', ''), 'NHS ', '')), ' ICB'), ' And ', ' & ') AS icb_name,
    stp.code AS icb_code,
    REPLACE(CONCAT(INITCAP(REPLACE(REPLACE(region.name, ' COMMISSIONING REGION', ''), 'NHS ', ''))), ' And ', ' & ') AS region_name,
    region.code AS region_code

FROM `ebmdatalab.hscic.practices` AS practice
INNER JOIN `hscic.pcns` AS pcn
    ON practice.pcn_id = pcn.code
INNER JOIN hscic.ccgs AS ccg
    ON practice.ccg_id = ccg.code
INNER JOIN hscic.stps AS stp
    ON ccg.stp_id = stp.code
INNER JOIN `hscic.regional_teams` AS region
    ON ccg.regional_team_id = region.code

WHERE setting = 4
  AND practice.close_date IS NULL