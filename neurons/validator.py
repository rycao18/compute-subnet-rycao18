# The MIT License (MIT)
# Copyright © 2023 Crazydevlegend

# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the “Software”), to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.

# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

# Step 1: Import necessary libraries and modules

import argparse
import ast
import os
import sys
import time
import traceback
from typing import List

import bittensor as bt
import torch
from cryptography.fernet import Fernet

import Validator.app_generator as ag
import Validator.calculate_score as cs
import Validator.database as db
import compute

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

blacklisted_hotkeys_set: set = set()
blacklisted_coldkeys_set: set = set()

SUSPECTED_MALICIOUS_COLDKEYS = []
SUSPECTED_MALICIOUS_HOTKEYS = [
    "5HZ1ATsziEMDm1iUqNWQatfEDb1JSNf37AiG8s3X4pZzoP3A",
    "5H679r89XawDrMhwKGH1jgWMZQ5eeJ8RM9SvUmwCBkNPvSCL",
    "5FnMHpqYo1MfgFLax6ZTkzCZNrBJRjoWE5hP35QJEGdZU6ft",
    "5H3tiwVEdqy9AkQSLxYaMewwZWDi4PNNGxzKsovRPUuuvALW",
    "5E6oa5hS7a6udd9LUUsbBkvzeiWDCgyA2kGdj6cXMFdjB7mm",
    "5DFaj2o2R4LMZ2zURhqEeFKXvwbBbAPSPP7EdoErYc94ATP1",
    "5H3padRmkFMJqZQA8HRBZUkYY5aKCTQzoR8NwqDfWFdTEtky",
    "5HBqT3dhKWyHEAFDENsSCBJ1ntyRdyEDQWhZo1JKgMSrAhUv",
    "5FAH7UesJRwwLMkVVknW1rsh9MQMUo78d5Qyx3KpFpL5A7LW",
    "5GUJBJmSJtKPbPtUgALn4h34Ydc1tjrNfD1CT4akvcZTz1gE",
    "5E2RkNBMCrdfgpnXHuiC22osAxiw6fSgZ1iEVLqWMXSpSKac",
    "5DaLy2qQRNsmbutQ7Havj49CoZSKksQSRkCLJsiknH8GcsN2",
    "5GNNB5kZfo6F9hqwXvaRfYdTuJPSzrXbtABzwoL499jPNBjt",
    "5GVjcJLQboN5NcQoP4x8oqovjAiEizdscoocWo9HBYYmPdR3",
    "5FswTe5bbs9n1SzaGpzUd6sDfnzdPfWVS2MwDWNbAneeT15k",
    "5F4bqDZkx79hCxmbbsVMuq312EW9hQLvsBzKsAJgcEqpb8L9"
]


def parse_list(input_string):
    """Very temporary TODO move to utils."""
    return ast.literal_eval(input_string)


# Step 2: Set up the configuration parser
# This function is responsible for setting up and parsing command-line arguments.
def get_config():
    parser = argparse.ArgumentParser()
    # Adds override arguments for network and netuid.
    parser.add_argument("--netuid", type=int, default=1, help="The chain subnet uid.")
    parser.add_argument("--auto_update", default="yes", help="Auto update")
    parser.add_argument(
        "--blacklist.suspected.hotkeys",
        dest="blacklist_suspected_hotkeys",
        default=True,
        action="store_true",
        help="Automatically use the list of internal suspected hotkeys.",
    )
    parser.add_argument(
        "--blacklisted.hotkeys",
        type=parse_list,
        dest="blacklisted_hotkeys",
        help="The list of the blacklisted hotkeys int the following format: \"['hotkey_x', '...']\"",
        default=[],
    )
    parser.add_argument(
        "--blacklist.suspected.coldkeys",
        dest="blacklist_suspected_coldkeys",
        default=True,
        action="store_true",
        help="Automatically use the list of internal suspected hotkeys.",
    )
    parser.add_argument(
        "--blacklisted.coldkeys",
        type=parse_list,
        dest="blacklisted_coldkeys",
        help="The list of the blacklisted coldkeys int the following format: \"['coldkeys_x', '...']\"",
        default=[],
    )

    # Adds subtensor specific arguments i.e. --subtensor.chain_endpoint ... --subtensor.network ...
    bt.subtensor.add_args(parser)
    # Adds logging specific arguments i.e. --logging.debug ..., --logging.trace .. or --logging.logging_dir ...
    bt.logging.add_args(parser)
    # Adds wallet specific arguments i.e. --wallet.name ..., --wallet.hotkey ./. or --wallet.path ...
    bt.wallet.add_args(parser)
    # Parse the config (will take command-line arguments if provided)
    config = bt.config(parser)

    if config.blacklist_suspected_hotkeys:
        for blacklisted_hotkey in SUSPECTED_MALICIOUS_HOTKEYS:
            config.blacklisted_hotkeys.append(blacklisted_hotkey)

    if config.blacklisted_coldkeys:
        for blacklisted_hotkey in SUSPECTED_MALICIOUS_COLDKEYS:
            config.blacklisted_hotkeys.append(blacklisted_hotkey)

    # Step 3: Set up logging directory
    # Logging is crucial for monitoring and debugging purposes.
    config.full_path = os.path.expanduser(
        "{}/{}/{}/netuid{}/{}".format(
            config.logging.logging_dir,
            config.wallet.name,
            config.wallet.hotkey,
            config.netuid,
            "validator",
        )
    )
    # Ensure the logging directory exists.
    if not os.path.exists(config.full_path):
        os.makedirs(config.full_path, exist_ok=True)

    # Return the parsed config.
    return config


# Filter the axons with uids_list, remove those with the same IP address.
def filter_axons(axons_list, uids_list):
    # Set to keep track of unique identifiers
    valid_ip_addresses = set()

    # List to store filtered axons
    filtered_axons = []
    filtered_uids = []
    filtered_hotkeys = []
    for index, axon in enumerate(axons_list):
        ip_address = axon.ip

        if ip_address not in valid_ip_addresses:
            valid_ip_addresses.add(ip_address)
            filtered_axons.append(axon)
            filtered_uids.append(uids_list[index])
            filtered_hotkeys.append(axon.hotkey)

    return filtered_axons, filtered_uids, filtered_hotkeys


def is_blacklisted(neuron):
    coldkey = neuron.axon_info.coldkey
    hotkey = neuron.axon_info.hotkey

    # Blacklist coldkeys that are blacklisted by user
    if coldkey in blacklisted_coldkeys_set:
        bt.logging.debug(f"Blacklisted recognized coldkey {coldkey} - with hotkey: {hotkey}")
        return True

    # Blacklist coldkeys that are blacklisted by user or by set of hotkeys
    if hotkey in blacklisted_hotkeys_set:
        bt.logging.debug(f"Blacklisted recognized hotkey {hotkey}")
        # Add the coldkey attached to this hotkey in the blacklisted coldkeys
        blacklisted_coldkeys_set.add(coldkey)
        return True


def get_valid_queryable_uids(metagraph, uids):
    valid_uids = []
    for index, uid in enumerate(uids):
        neuron = metagraph.neurons[uid]

        if neuron.axon_info.ip != "0.0.0.0" and metagraph.total_stake[index] < 1.024e3 and not is_blacklisted(neuron=neuron):
            valid_uids.append(uid)

    return valid_uids


def get_valid_tensors(metagraph):
    tensors = []
    for uid in metagraph.uids:
        neuron = metagraph.neurons[uid]

        if neuron.axon_info.ip != "0.0.0.0" and not is_blacklisted(neuron=neuron):
            tensors.append(True)
        else:
            tensors.append(False)

    return tensors


def main(config):
    global blacklisted_hotkeys_set
    global blacklisted_coldkeys_set

    # Set up logging with the provided configuration and directory.
    bt.logging(config=config, logging_dir=config.full_path)
    bt.logging.info(f"Running validator for subnet: {config.netuid} on network: {config.subtensor.chain_endpoint} with config:")
    # Log the configuration for reference.
    bt.logging.info(config)

    # Step 4: Build Bittensor validator objects
    # These are core Bittensor classes to interact with the network.
    bt.logging.info("Setting up bittensor objects.")

    # The wallet holds the cryptographic key pairs for the validator.
    wallet = bt.wallet(config=config)
    bt.logging.info(f"Wallet: {wallet}")

    # The subtensor is our connection to the Bittensor blockchain.
    subtensor = bt.subtensor(config=config)
    bt.logging.info(f"Subtensor: {subtensor}")

    # Dendrite is the RPC client; it lets us send messages to other nodes (axons) in the network.
    dendrite = bt.dendrite(wallet=wallet)
    bt.logging.info(f"Dendrite: {dendrite}")

    # The metagraph holds the state of the network, letting us know about other miners.
    metagraph = subtensor.metagraph(config.netuid)
    bt.logging.info(f"Metagraph: {metagraph}")

    # Optimize the blacklist list
    blacklisted_hotkeys_set = {blacklisted_hotkey for blacklisted_hotkey in config.blacklisted_hotkeys}
    blacklisted_coldkeys_set = {blacklisted_coldkey for blacklisted_coldkey in config.blacklisted_coldkeys}

    # Step 5: Connect the validator to the network
    if wallet.hotkey.ss58_address not in metagraph.hotkeys:
        bt.logging.error(f"\nYour validator: {wallet} if not registered to chain connection: {subtensor} \nRun btcli register and try again.")
        exit()
    else:
        # Each miner gets a unique identity (UID) in the network for differentiation.
        my_subnet_uid = metagraph.hotkeys.index(wallet.hotkey.ss58_address)
        bt.logging.info(f"Running validator on uid: {my_subnet_uid}")

    # Step 6: Set up initial scoring weights for validation
    bt.logging.info("Building validation weights.")

    # Initialize alpha
    alpha = 0.9

    # Initialize weights for each miner, store current uids.
    last_uids = metagraph.uids.tolist()
    scores = torch.zeros(len(last_uids), dtype=torch.float32)

    curr_block = subtensor.block
    last_updated_block = curr_block - (curr_block % 100)

    # Step 7: The Main Validation Loop
    bt.logging.info("Starting validator loop.")
    step = 0
    while True:
        try:
            # Sync the subtensor state with the blockchain.
            if step % 5 == 0:
                bt.logging.info(f"🔄 Syncing metagraph with subtensor.")

                # Resync our local state with the latest state from the blockchain.
                metagraph = subtensor.metagraph(config.netuid)

                # Sync scores with metagraph
                # Get the current uids of all miners in the network.
                uids = metagraph.uids.tolist()
                # Create new_scores with current metagraph
                new_scores = torch.zeros(len(uids), dtype=torch.float32)

                for index, uid in enumerate(uids):
                    try:
                        last_index = last_uids.index(uid)
                        new_scores[index] = scores[last_index]
                    except ValueError:
                        # New node
                        new_scores[index] = 0
                last_uids = uids

                # Set the weights of validators to zero.
                scores = new_scores * (metagraph.total_stake < 1.024e3)
                # Set the weight to zero for all nodes without assigned IP addresses.
                scores = scores * torch.Tensor(get_valid_tensors(metagraph=metagraph))

                bt.logging.info(f"🔢 Initialized scores : {scores.tolist()}")

            if step % 10 == 0:
                # Check for auto update
                if config.auto_update == "yes":
                    compute.util.try_update()
                # Filter axons with stake and ip address.
                queryable_uids = get_valid_queryable_uids(metagraph, uids)
                queryable_axons = [metagraph.axons[metagraph.uids.tolist().index(uid)] for uid in queryable_uids]
                axons_list, uids_list, hotkeys_list = filter_axons(
                    axons_list=queryable_axons,
                    uids_list=queryable_uids,
                )

                # Prepare app_data for benchmarking
                # Generate secret key for app
                secret_key = Fernet.generate_key()
                cipher_suite = Fernet(secret_key)
                # Compile the script and generate an exe.
                ag.run(secret_key)
                try:
                    main_dir = os.path.dirname(os.path.abspath(__file__))
                    file_name = os.path.join(main_dir, "Validator/dist/script")
                    # Read the exe file and save it to app_data.
                    with open(file_name, "rb") as file:
                        # Read the entire content of the EXE file
                        app_data = file.read()
                except Exception as e:
                    bt.logging.error(f"{e}")
                    continue
                # Query the miners for benchmarking
                bt.logging.info(f"🆔 Benchmarking uids : {uids_list}")
                responses: List[compute.protocol.PerfInfo] = dendrite.query(
                    axons_list,
                    compute.protocol.PerfInfo(perf_input=repr(app_data)),
                    timeout=120,
                )

                # Format responses and save them to benchmark_responses
                benchmark_responses = []
                for index, response in enumerate(responses):
                    try:
                        if response:
                            binary_data = ast.literal_eval(response)  # Convert str to binary data
                            decoded_data = ast.literal_eval(cipher_suite.decrypt(binary_data).decode())  # Decrypt data and convert it to object
                            benchmark_responses.append(decoded_data)
                        else:
                            benchmark_responses.append({})
                    except Exception as e:
                        # bt.logging.error(f"Error parsing response: {e}")
                        benchmark_responses.append({})

                bt.logging.info(f"✅ Benchmark results : {benchmark_responses}")

                db.update(hotkeys_list, benchmark_responses)

                # Calculate score
                score_uid_dict = {}
                for index, uid in enumerate(metagraph.uids):
                    score = 0
                    try:
                        uid_index = uids_list.index(uid)
                        score = cs.score(benchmark_responses[uid_index], axons_list[uid_index].hotkey)
                        score = min(score, 100)
                    except (ValueError, KeyError):
                        score = 0

                    # Update the global score of the miner.
                    # This score contributes to the miner's weight in the network.
                    # A higher weight means that the miner has been consistently responding correctly.
                    scores[index] = alpha * scores[index] + (1 - alpha) * score
                    score_uid_dict[uid.item()] = scores[index].item()

                bt.logging.info(f"🔢 Updated scores : {score_uid_dict}")

            # Periodically update the weights on the Bittensor blockchain.
            current_block = subtensor.block
            if current_block - last_updated_block > 100:
                weights = torch.nn.functional.normalize(scores, p=1.0, dim=0)
                bt.logging.info(f"🏋️ Weight of miners : {weights.tolist()}")
                # This is a crucial step that updates the incentive mechanism on the Bittensor blockchain.
                # Miners with higher scores (or weights) receive a larger share of TAO rewards on this subnet.
                result = subtensor.set_weights(
                    netuid=config.netuid,  # Subnet to set weights on.
                    wallet=wallet,  # Wallet to sign set weights using hotkey.
                    uids=metagraph.uids,  # Uids of the miners to set weights for.
                    weights=weights,  # Weights to set for the miners.
                    wait_for_inclusion=False,
                )
                last_updated_block = current_block
                if result:
                    bt.logging.success("Successfully set weights.")
                else:
                    bt.logging.error("Failed to set weights.")

            # End the current step and prepare for the next iteration.
            step += 1
            # Sleep for a duration equivalent to the block time (i.e., time between successive blocks).
            time.sleep(bt.__blocktime__)

        # If we encounter an unexpected error, log it for debugging.
        except RuntimeError as e:
            bt.logging.error(e)
            traceback.print_exc()

        # If the user interrupts the program, gracefully exit.
        except KeyboardInterrupt:
            bt.logging.success("Keyboard interrupt detected. Exiting validator.")
            exit()


# The main function parses the configuration and runs the validator.
if __name__ == "__main__":
    # Parse the configuration.
    config = get_config()
    # Run the main function.
    main(config)
