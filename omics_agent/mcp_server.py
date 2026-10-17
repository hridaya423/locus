from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer

load_dotenv()

from . import agent, samples  # noqa: E402  (needs the API key loaded first)

mcp = MCPServer("omics-agent")


@mcp.tool()
def search_datasets(question: str, limit_per_repository: int = 40) -> dict:
    """Find public omics datasets (GEO, ArrayExpress, ENA, PRIDE, MassIVE, MetaboLights, CELLxGENE and more) for a research question in plain English.

    Returns each relevant dataset with a grade (strong or partial), four checks (same disease,
    patient material, requested data type, controls), case and control sample counts read from
    the sample records where available, a reason, a verbatim quote from the dataset metadata,
    and a link. Also returns groups of datasets that come from the same paper. Takes about a minute.
    """
    return agent.run(question, limit_per_repository)


@mcp.tool()
def geo_sample_groups(accession: str, topic: str) -> dict:
    """Count disease (case) and control samples in one GEO series (for example GSE326573) from its sample records.

    `topic` is the disease or condition that counts as a case, for example "idiopathic pulmonary fibrosis".
    """
    fields, source = samples.gemma_fields(accession), "samples, groups curated by Gemma"
    if not fields:
        fields, source = samples.geo_fields(accession), "GEO sample records"
    labels = agent._ask(samples.label_prompt(topic, accession, fields), samples.LABEL_SCHEMA, effort="low")
    return samples.count(fields, labels, source) | {"group_field": labels["group_field"]}


def main() -> None:
    mcp.run()
