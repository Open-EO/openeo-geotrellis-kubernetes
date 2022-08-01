# Running openEO Geotrellis backend on Slurm/HPC

This readme explains the basic steps to run openEO jobs on HPC, using the SLURM job scheduler.


Tests were carried out on the [SURF HPC cluster](https://www.surf.nl/en/hpc-cloud-your-flexible-compute-infrastructure) in the frame of the C-Scale H2020 project.

## Preconditions
Not every HPC is the same. These are the assumptions on the environment, which hold true for the SURF HPC.

- Singularity to run jobs inside a container.
- SLURM is used as job scheduler
- EO Data for this test is read from a remote location, so no local data is needed.
- Configuration files are stored in a shared directory mounted under /home, which is also accessible within Singularity containers



## Running a batch job

In this experiment, we do not run the full openEO web service on an HPC, but directly start a batch job instead.
The job specification is based on the openEO standard, but the job submission script is custom to the used backend and scheduler.

These are the main configuration files:

- **/home/sram-cscale_test-jdries/OPENEO/job_specification.json** Contains the standardized openEO job specification
- **/home/sram-cscale_test-jdries/OPENEO/layercatalog.json** Contains the configuration for the openEO collections. This specification contains a few custom elements, but is largely based on STAC collections.


Steps to run a job:
1. clone this repository into a directory that is available on the HPC.
2. Pull docker image and convert to singularity: singularity pull docker://vito-docker-private-dev.artifactory.vgt.vito.be/openeo-yarn **As of writing, this image still requires a login, need check if it can move to a public repo.**
3. In openeo_batch.sh, make sure that paths to the singularity image, layer catalog, working dir and job spec are correct.
4. Submit SLURM job ``sbatch openeo_batch.sh ``



