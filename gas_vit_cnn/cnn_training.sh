#!/bin/bash
#SBATCH -c 1                # Number of cores (-c)
#SBATCH -t 0-10:00          # Runtime in D-HH:MM, minimum of 10 minutes
#SBATCH -p gpu_test        # Partition to submit to
#SBATCH --gres=gpu
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G           # Memory pool for all cores (see also --mem-per-cpu)
#SBATCH -o myoutput_%j.out  # File to which STDOUT will be written, %j inserts jobid
#SBATCH -e myerrors_%j.err  # File to which STDERR will be written, %j inserts jobid
#SBATCH --mail-user=msl63@cam.ac.uk

# load modules
module load python

mamba activate env 

# run code
python cnn_training.py