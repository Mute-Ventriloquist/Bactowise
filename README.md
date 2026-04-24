# BactoWise

**Complete bacterial genome characterisation — multi-tool annotation, AMR profiling, and functional analysis, automated.**

BactoWise runs a full genome analysis pipeline from a single FASTA file. It handles conda environments, Singularity containers, and database downloads automatically. You provide a genome and an organism name — BactoWise does the rest.

```
Stage 1  CheckM                                  QC — completeness & contamination
Stage 2  Prokka + Bakta + PGAP                   Gene annotation (parallel)
Stage 3  Consensus Engine                         Single authoritative annotation
Stage 4  AMRFinderPlus · Phigaro · Platon         AMR, prophages, plasmids,
         MEFinder · EggNOG-mapper · SPIFinder*    MGEs, GO/KEGG, SPIs
```
*SPIFinder runs only for Salmonella genomes.

---

## Prerequisites

- **Conda** (Miniconda or Mambaforge)
- **Singularity or Apptainer** — required for Bakta and PGAP

```bash
# HPC cluster
module load singularity

# Local workstation (Ubuntu / WSL2)
sudo add-apt-repository -y ppa:apptainer/ppa && sudo apt update && sudo apt install -y apptainer
```

---

## Install

```bash
conda build conda_recipe/ -c bioconda -c conda-forge
conda install --use-local bactowise -c bioconda -c conda-forge
```

> WSL users: if `conda build` fails with a syntax error, see [Installation](DOCS.md#1-installation).

---

## Quick start

```bash
bactowise run -f genome.fasta -n "Genus species"
```

BactoWise sets up conda environments, pulls container images, and downloads any missing databases automatically on first run. Results land in `./results/`.

> **Note:** The PGAP (~38 GB) and EggNOG-mapper (~48 GB) databases are large enough that pre-downloading is strongly recommended before your first full run — see [Databases](DOCS.md#2-databases).

---

## Common options

| Flag | Description |
|---|---|
| `-f` / `--fasta` | Input genome (required) |
| `-n` / `--organism` | NCBI Taxonomy name, e.g. `"Salmonella enterica"` (required) |
| `-o` / `--output` | Output directory (default: `./results`) |
| `--threads N` | CPU threads for all tools (default: 4 from pipeline.yaml) |
| `--skip stage_1` | Skip QC (CheckM) |
| `--skip stage_4` | Skip supplementary annotations |
| `--gff tool:path` | Provide pre-computed GFF for any annotation tool |

```bash
# Skip QC, use 8 threads, write to a custom output directory
bactowise run -f genome.fasta -n "Escherichia coli" --skip stage_1 --threads 8 -o /scratch/ecoli

# Provide a pre-computed Bakta annotation, run Prokka and PGAP fresh
bactowise run -f genome.fasta -n "Staphylococcus aureus" --gff bakta:/prev/run/bakta.gff3
```

---

## Storage

| Database | Size | Command |
|---|---|---|
| CheckM | ~1.4 GB | `bactowise db download --checkm` |
| Bakta | ~4 GB | `bactowise db download --bakta` |
| PGAP | ~38 GB | `bactowise db download --pgap` |
| Platon | ~2.8 GB | `bactowise db download --platon` |
| EggNOG-mapper | ~48 GB | `bactowise db download --eggnog` |
| SPIFinder | ~3 MB | `bactowise db download --spifinder` |
| **Total** | **~96 GB** | run each command above |

PGAP also requires ~60 GB of working space during a run. Plan for ~160 GB of free disk before running the full pipeline.

Check database status at any time:
```bash
bactowise db status
```

---

## Documentation

- **[User Guide](DOCS.md#user-guide)** — detailed flags, QC output, per-tool documentation, troubleshooting
- **[Developer Guide](DOCS.md#developer-guide)** — pipeline.yaml reference, adding new tools, modifying defaults
