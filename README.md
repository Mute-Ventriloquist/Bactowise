# Genoflow

Annotate bacterial genomes using **Prokka** and **Bakta** simultaneously — one command, one config file.

---

## What you need before starting (one-time setup)

### 1. Install Docker Desktop
Docker runs Bakta inside a sealed container so you don't have to install it manually.

| OS | Steps |
|---|---|
| **Mac** | Download from [docker.com](https://docker.com) → drag to Applications → open it. You'll see a whale 🐳 in your menu bar when it's running. |
| **Windows** | Download installer from [docker.com](https://docker.com) → run it → start Docker Desktop from the Start menu. |
| **Linux** | `sudo apt install docker.io && sudo systemctl start docker` then run `sudo usermod -aG docker $USER && newgrp docker` to grant your user permission. If `newgrp` doesn't work, close and reopen your terminal. |

**Verify Docker is working:**
```bash
docker run hello-world
# Should print: "Hello from Docker!"
```

**Start/stop Docker daemon (if the whale isn't running):**
```bash
# Mac/Windows: just open Docker Desktop from your Applications/Start menu

# Linux only:
sudo systemctl start docker    # start
sudo systemctl stop docker     # stop
sudo systemctl status docker   # check if running
```

---

### 2. Build the package locally
From the root of the `genoflow` project directory, run:

```bash
conda build conda_recipe/ -c bioconda -c conda-forge
```

This compiles the package and stores it in your local conda channel. It will also automatically run `run_tests.sh` at the end to verify the build. The build output will tell you the exact path where the built package was saved (something like `/home/you/anaconda3/conda-bld/linux-64/genoflow-0.1.0-py311_0.tar.bz2`).

### 3. Install Genoflow from your local build
```bash
conda install --use-local genoflow -c bioconda -c conda-forge
```

`--use-local` tells conda to install from your machine's local build rather than looking it up online.

---

### 4. Download the Bakta database (one-time, ~2 GB)
```bash
bakta_db download --output ~/bakta_db --type light
```

---

### 5. Download the test genome (optional but recommended)
```bash
# M. genitalium G37 — the "Hello World" of bacterial genomes (~580 kb, very fast)
efetch -db nucleotide -id NC_000908.2 -format fasta > mgenitalium.fasta
```
Or just open this URL in your browser and save the file:
`https://www.ncbi.nlm.nih.gov/nuccore/NC_000908.2?report=fasta`

---

## Running the pipeline

**Step 1 — Edit the config file** (`pipeline.yaml`):
```yaml
tools:
  - name: prokka
    version: "1.14.6"
    runtime: conda
    params:
      genus: "Mycoplasma"
      species: "genitalium"

  - name: bakta
    version: "1.9.3"
    runtime: docker
    image: "oschwengers/bakta:1.9.3"
    database:
      path: "~/bakta_db"      # ← change this if you saved the DB elsewhere
      type: light
    params: {}

output_dir: "./results"
threads: 4
```

**Step 2 — Run it:**
```bash
genoflow -f mgenitalium.fasta -c pipeline.yaml
```

**Step 3 — Find your results:**
```
results/
├── prokka/        ← Prokka annotation output
│   └── logs/
└── bakta/         ← Bakta annotation output
    └── logs/
```

---

## Other useful commands

```bash
genoflow validate -c pipeline.yaml   # check config without running anything
genoflow --help                      # see all options
```

## Swapping Bakta → PGAP later

Change two lines in `pipeline.yaml`, nothing else:
```yaml
  - name: pgap
    version: "2024-07-18.build7555"
    runtime: docker
    image: "ncbi/pgap:2024-07-18.build7555"
    database:
      path: "~/pgap_db"
```

## Troubleshooting

| Error | Fix |
|---|---|
| `Cannot connect to Docker` | Open Docker Desktop, wait for whale 🐳 to stop animating |
| `Database not found at ~/bakta_db` | Run `bakta_db download --output ~/bakta_db --type light` |
| `prokka not found on PATH` | Run `conda install -c bioconda prokka` |
| `genoflow: command not found` | Run `conda activate <your-env>` first |
