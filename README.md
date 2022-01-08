# Script for automatic creation of GPU servers in CloudSigma

## Installation

Create a python 3 virtual environment:

```
python3 -m venv /path/to/new/virtual/environment
```

Activate the virtual environment:

```
source <venv>/bin/activate
```

Install the required packages:

```
pip install -r <scriptpath>/requirements.txt
```

## Configuration

In the root path of this repository you'll find a file called: `config.ini`.
Example config:

```
[main]
gpus = 1 
gpu_model = nvidia_a6000
grey = False
server_cpu = 2
server_mem = 2
cpu_type = amd
drive = 09c7c610-7201-49cc-b7a3-25f8fae23dd9
pubkey = 12671cd1-29b0-4157-a031-ad98d8ac9a7f
unique_name = zzz
public_network = True
private_network = False
vlan_uuid = a3d41a4d-ac79-442f-8ede-c86672eceacf 
auto_adjust_max_gpus = True
iteration_pause_sec = 5
```

The basic server attributes are defined first. The amount of GPUs attached to each server, the model of the GPU, whether the server is backfilling or not (`grey`), the compute parameters in GHz and GB and the CPU type.
The drive indicates a golden image to be used for all servers, same applies for the pubkey.
This is the public key resource, created in CS which will be attached to all servers.
The unique name is a string to identify the servers created by this config.
Public and private network indicate whether the server should have either of these or both, the public network is configured with DHCP by default. If the private option is set, then a VLAN UUID needs to be defined below. The `auto_adjust_max_gpus` enables the script to automatically size down the GPU configuration of the server if not enough are available. The last option is a pause interval between each iteration of the server create process.

## Running

The script can be run directly or as a systemd service which will run in the background and can be set to automatically start and restart.
For a direct run, simply set the needed configuration and run directly within the virtual environment:

```
python backfill.py
```

When running as a systemd service, you need to edit the service file in this repository with the correct paths.
Optionally the service can be enabled on boot:

```
sudo systemctl enable backfill.service
```

Starting the service:

```
sudo systemctl start backfill.service
```
