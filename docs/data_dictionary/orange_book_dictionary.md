# FDA Orange Book Data Dictionary

Source: FDA Approved Drug Products with Therapeutic Equivalence Evaluations (Orange Book).
Files: `Orange_book_data_files/products.txt`, `patent.txt`, `exclusivity.txt`
Format: tilde (`~`) delimited text, latin-1 encoding, updated monthly by FDA.

---

## products.txt

| Field | Description |
|-------|-------------|
| Ingredient | Active ingredient (INN/USAN name). Example: `ARIPIPRAZOLE`. Used to group therapeutically equivalent products. |
| DF;Route | Dosage form and route of administration. Example: `TABLET;ORAL`, `INJECTABLE;INJECTION`. Semicolon separates form from route. |
| Trade_Name | Brand name of the product. Example: `ABILIFY`. Used to match NADAC brand entries. |
| Applicant | Abbreviated applicant name. |
| Strength | Labeled strength. Example: `10MG`, `5 MG/ML`. |
| Appl_Type | Application type: `N` = NDA (brand/innovator), `A` = ANDA (generic). |
| Appl_No | FDA application number. |
| Product_No | Product number within the application. |
| TE_Code | Therapeutic equivalence code. Key values: `AB` = therapeutically equivalent generic, `AB1`/`AB2` = multiple AB generics for same brand, `AT` = topical equivalent, `AP` = parenteral equivalent, `BX` = insufficient data, blank = not rated. **AB is the gold standard for substitution.** |
| Approval_Date | Date of FDA approval. |
| RLD | Reference Listed Drug: `Yes` = this is the reference product that generics are tested against. |
| RS | Reference Standard: `Yes` = this product is the FDA reference standard for bioequivalence testing. |
| Type | `RX` = prescription, `OTC` = over-the-counter, `DISCN` = discontinued. |
| Applicant_Full_Name | Full legal name of the applicant. |

### Key Derived Fields (added in `marts.orange_book_products_clean`)

| Field | Formula |
|-------|---------|
| `application_category` | `N` → `NDA_BRAND`, `A` → `ANDA_GENERIC` |
| `is_rld` | 1 if `RLD = YES` |
| `is_rs` | 1 if `RS = YES` |

### How to Find Generic Alternatives

```sql
-- Step 1: Find the brand's equivalence group
SELECT ingredient, dosage_form_route, strength, te_code
FROM marts.orange_book_products_clean
WHERE trade_name = 'ABILIFY' AND appl_type = 'N';
-- → ingredient=ARIPIPRAZOLE, te_code=AB

-- Step 2: Find all ANDA generics in the same group
SELECT trade_name, appl_type
FROM marts.orange_book_products_clean
WHERE ingredient = 'ARIPIPRAZOLE'
  AND te_code = 'AB'
  AND appl_type = 'A';
-- → ARIPIPRAZOLE generics from multiple manufacturers
```

---

## patent.txt

| Field | Description |
|-------|-------------|
| Appl_Type | N or A |
| Appl_No | FDA application number |
| Product_No | Product number |
| Patent_No | US patent number |
| Patent_Expire_Date_Text | Expiration date (text format) |
| Drug_Substance_Flag | Y = patent covers the drug substance |
| Drug_Product_Flag | Y = patent covers the drug product formulation |
| Patent_Use_Code | Use code (e.g. U-141) if method-of-use patent |
| Delist_Flag | Y = patent delisted |
| Submission_Date | Date patent was submitted to FDA |

Use for: identifying brand protection, patent expiry dates, and potential generic entry windows.

---

## exclusivity.txt

| Field | Description |
|-------|-------------|
| Appl_Type | N or A |
| Appl_No | FDA application number |
| Product_No | Product number |
| Exclusivity_Code | Code for the type of exclusivity (e.g. NCE, ODE, RTO) |
| Exclusivity_Date | Date when exclusivity expires |

Use for: identifying why no generic may exist yet (market exclusivity prevents ANDA approval).

---

## Therapeutic Equivalence Code Reference

| Code | Meaning | Switch Confidence |
|------|---------|-----------------|
| AB, AB1, AB2 | FDA-approved therapeutic equivalent; same ingredient, form, route, strength | High (0.95) |
| AT | Topical equivalent | High for same route |
| AP | Parenteral equivalent | High for same route |
| BX | Therapeutic equivalence data insufficient | Low (0.60) |
| (blank) | Not yet evaluated or not applicable | Low (0.60) |

Source: FDA Orange Book Introduction, [www.fda.gov/drugs](https://www.fda.gov/drugs/drug-approvals-and-databases/approved-drug-products-therapeutic-equivalence-evaluations-orange-book).
