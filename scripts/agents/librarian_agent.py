"""
Librarian Agent: drug identity and mapping.

Responsible for determining whether a brand drug has an FDA-approved generic
alternative using the Orange Book + NADAC equivalence map. Returns structured
DrugMapping — never makes clinical equivalence claims beyond TE code data.
"""

from scripts.models.schemas import ClaimRecord, DrugMapping
from scripts.services.drug_mapping_service import map_drug


def run(claim: ClaimRecord) -> DrugMapping:
    return map_drug(claim.drug_name, claim.ndc)
