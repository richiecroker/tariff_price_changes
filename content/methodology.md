We use the [Part VIIIA Drug Tariff data](https://www.nhsbsa.nhs.uk/pharmacies-gp-practices-and-appliance-contractors/drug-tariff/drug-tariff-part-viii) available from the NHS Business Services Authority.  This is generally available three working days before the appropriate month.
        
The prescribing data comes from the [English Prescribing Dataset](https://opendata.nhsbsa.net/dataset/english-prescribing-dataset-epd-with-snomed-code), also supplied by the NHS Business Services Authority.

The estimator calculates the changes in the following way:

1.  Our code compares the price of every Virtual Medicinal Product Pack (VMPP) level presentation in Part VIIIA of the Drug Tariff with the previous month's price.  If it finds that it's different, it's included in our analysis.
2.  We then subtract the new price from the old price, and divide by the quantity in the pack, which gives us our 1price difference per unit1.
3.  We adjust the DT prices to the "actual cost" prices by adjusting for discount levels described by the NHS Business Services Authority [Drug Tariff deduction scale](https://www.nhsbsa.nhs.uk/drug-tariff-deduction-scale). 
**NOTE** we don't yet distinguish for "zero-discount" products - this will be addressed in a later version.
3.  Sometimes there are multiple packs available for one presentation (for example: [paracetamol 500mg tablets has a tariff price for 32 and 100 tablets](https://openprescribing.net/tariff/?codes=0407010H0AAAMAM).  The prescribing data doesn't allow us to distinguish betwen these packs, so we identify which pack as the highest absolute change per unit, and use that. (If there's a tie, it just picks one, so we don't duplicate the calculation).
4.  We've now got a list of price changes for each drug for the previous month.  We then join in to the latest prescribing data in our system, which is usually 2-3 months behind the Drug Tariff data.  We then multiply the `price different per unit` by the `total quantity` prescribed by each practice in that month, which gives us the estimated change for one month's prescribing.  We can then aggregate that up for PCNs, ICBs, etc.

**Assumptions and limitations**
- Prescribing data is only used for GP practices who are shown as open at the time of the prescribing data.  Not non-GP practices, e.g. other services such as out-of-hours or non-NHS providers having an ICB FP10 prescribing code are included in the analysis.
- Prescribing data is a few months behind, and therefore there may be some differences between the quantities used for the estimation and actual prescribing, particularly where there are differences in the number of dispensing days.  We are hoping to publish the impact of this on our Price Concessions estimator later this year.
- Price concessions are not included in this estimation - only Drug Tariff changes are included.
