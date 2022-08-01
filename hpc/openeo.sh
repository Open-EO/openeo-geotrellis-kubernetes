#!/bin/bash
#SBATCH --time=00:01:00
#SBATCH --nodes=2
#SBATCH --ntasks=3
#SBATCH --cpus-per-task=1
#SBATCH --mem=3G

printenv | grep SLURM

export WORK_DIR=/project/cscale_test/Public/openeo/openeo-geotrellis-kubernetes/hpc

# Recommended settings for calling Intel MKL routines from multi-threaded applications
# https://software.intel.com/en-us/articles/recommended-settings-for-calling-intel-mkl-routines-from-multi-threaded-applications
export MKL_NUM_THREADS=1
export SPARK_IDENT_STRING=$SLURM_JOBID
export SPARK_WORKER_DIR=$TMPDIR
export SLURM_SPARK_MEM=$(printf "%.0f" $((${SLURM_MEM_PER_NODE} * 95/100)))
export SPARK_HOME=/opt/spark3.2.0
export SPARK_LOG_DIR=${WORK_DIR}
export SPARK_CONF_DIR=${WORK_DIR}/conf
#export SPARK_MASTER_PORT=8082
#export SPARK_MASTER_HOST=10.0.3.133


singularity exec  /project/cscale_test/Public/openeo/openeo-yarn_latest.sif /opt/spark3.2.0/sbin/start-master.sh
sleep 5
MASTER_URL=$(grep -Po '(?=spark://).*' $SPARK_LOG_DIR/spark-${SPARK_IDENT_STRING}-org.apache.spark.deploy.master*.out)

NWORKERS=$((SLURM_NTASKS - 2))
SPARK_NO_DAEMONIZE=1 srun -n ${NWORKERS} -N ${NWORKERS} --label --output=$SPARK_LOG_DIR/spark-%j-workers.out singularity exec /project/cscale_test/Public/openeo/openeo-yarn_latest.sif /opt/spark3.2.0/sbin/start-worker.sh -m ${SLURM_SPARK_MEM}M -c ${SLURM_CPUS_PER_TASK} -d ${SPARK_WORKER_DIR} ${MASTER_URL} &
slaves_pid=$!

export TRAVIS=1
export PYTHONPATH=/opt/venv/lib64/python3.8/site-packages
export OPENEO_CATALOG_FILES=/opt/layercatalog.json
srun -n 1 -N 1 singularity exec /project/cscale_test/Public/openeo/openeo-yarn_latest.sif /opt/spark3.2.0/bin/spark-submit --master ${MASTER_URL} --executor-memory ${SLURM_SPARK_MEM}M /opt/venv/lib64/python3.8/site-packages/openeogeotrellis/deploy/kube.py

kill $slaves_pid
singularity exec /project/cscale_test/Public/openeo/openeo-yarn_latest.sif /opt/spark3.2.0/sbin/stop-master.sh
