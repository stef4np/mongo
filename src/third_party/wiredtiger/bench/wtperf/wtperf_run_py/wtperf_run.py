#!/usr/bin/python
# -*- coding: utf-8 -*-

#
# Public Domain 2014-present MongoDB, Inc.
# Public Domain 2008-2014 WiredTiger, Inc.
#
# This is free and unencumbered software released into the public domain.
#
# Anyone is free to copy, modify, publish, use, compile, sell, or
# distribute this software, either in source code form or as a compiled
# binary, for any purpose, commercial or non-commercial, and by any
# means.
#
# In jurisdictions that recognize copyright laws, the author or authors
# of this software dedicate any and all copyright interest in the
# software to the public domain. We make this dedication for the benefit
# of the public at large and to the detriment of our heirs and
# successors. We intend this dedication to be an overt act of
# relinquishment in perpetuity of all present and future rights to this
# software under copyright law.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
# IN NO EVENT SHALL THE AUTHORS BE LIABLE FOR ANY CLAIM, DAMAGES OR
# OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
# ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
# OTHER DEALINGS IN THE SOFTWARE.

import argparse
import os.path
import platform
import psutil
import subprocess
import sys
import json
from perf_stat import PerfStat
from perf_stat_collection import PerfStatCollection
from pygit2 import discover_repository, Repository
from pygit2 import GIT_SORT_NONE
from typing import Dict, List, Tuple
from wtperf_config import WTPerfConfig


def create_test_home_path(home: str, test_run: int, index:int):
    home_path = "{}_{}_{}".format(home, index, test_run)
    return home_path


def get_git_info(git_working_tree_dir):
    repository_path = discover_repository(git_working_tree_dir)
    assert repository_path is not None

    repo = Repository(repository_path)
    commits = list(repo.walk(repo.head.target, GIT_SORT_NONE))
    head_commit = commits[0]
    diff = repo.diff()

    git_info = {
        'head_commit': {
            'hash': head_commit.hex,
            'message': head_commit.message,
            'author': head_commit.author.name
            },
        'branch': {
            'name': repo.head.shorthand
        },
        'stats': {
            'files_changed': diff.stats.files_changed,
        },
        'num_commits': len(commits)
    }

    return git_info


def construct_wtperf_command_line(wtperf: str, env: str, test: str, home: str, arguments: List[str]):
    command_line = []
    if env is not None:
        command_line.append(env)
    command_line.append(wtperf)
    if test is not None:
        command_line.append('-O')
        command_line.append(test)
    if arguments is not None:
        command_line.extend(arguments)
    if home is not None:
        command_line.append('-h')
        command_line.append(home)
    return command_line

def to_value_list(reported_stats: List[PerfStat], brief: bool):
    stats_list = []
    for stat in reported_stats:
        stat_list = stat.get_value_list(brief = brief)
        stats_list.extend(stat_list)
    return stats_list

def brief_perf_stats(config: WTPerfConfig, reported_stats: List[PerfStat]):
    as_list = [{
        "info": {
            "test_name": os.path.basename(config.test)
        },
        "metrics": to_value_list(reported_stats, brief=True)
    }]
    return as_list


def detailed_perf_stats(config: WTPerfConfig, reported_stats: List[PerfStat]):
    total_memory_gb = psutil.virtual_memory().total / (1024 * 1024 * 1024)
    as_dict = {
                'Test Name': os.path.basename(config.test),
                'config': config.to_value_dict(),
                'metrics': to_value_list(reported_stats, brief=False),
                'system': {
                   'cpu_physical_cores': psutil.cpu_count(logical=False),
                   'cpu_logical_cores': psutil.cpu_count(),
                   'total_physical_memory_gb': total_memory_gb,
                   'platform': platform.platform()
                }
            }

    if config.git_root:
        as_dict['git'] = get_git_info(config.git_root)

    return as_dict


def run_test_wrapper(config: WTPerfConfig, index: int = 0, arguments: List[str] = None):
    for test_run in range(config.run_max):
        print("Starting test  {}".format(test_run))
        run_test(config=config, test_run=test_run, index=index, arguments=arguments)
        print("Completed test {}".format(test_run))


def run_test(config: WTPerfConfig, test_run: int, index: int = 0, arguments: List[str] = None):
    test_home = create_test_home_path(home=config.home_dir, test_run=test_run, index=index)
    if config.verbose:
        print("Home directory path created: {}".format(test_home))
    command_line = construct_wtperf_command_line(
        wtperf=config.wtperf_path,
        env=config.environment,
        arguments=arguments,
        test=config.test,
        home=test_home)
    try:
        subprocess.run(command_line, check=True, stderr=subprocess.STDOUT, stdout=subprocess.PIPE,
                       universal_newlines=True)
    except subprocess.CalledProcessError as cpe:
        print("Error: {}".format(cpe.output))
        exit(1)


def process_results(config: WTPerfConfig, perf_stats: PerfStatCollection, index: int = 0) -> List[PerfStat]:
    for test_run in range(config.run_max):
        test_home = create_test_home_path(home=config.home_dir, test_run=test_run, index=index)
        if config.verbose:
            print('Reading stats from {} directory.'.format(test_home))
        perf_stats.find_stats(test_home=test_home)
    return perf_stats.to_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--wtperf', help='path of the wtperf executable')
    parser.add_argument('-e', '--env', help='any environment variables that need to be set for running wtperf')
    parser.add_argument('-t', '--test', help='path of the wtperf test to execute')
    parser.add_argument('-o', '--outfile', help='path of the file to write test output to')
    parser.add_argument('-b', '--brief_output', action="store_true", help='brief (not detailed) test output')
    parser.add_argument('-m', '--runmax', type=int, default=1, help='maximum number of times to run the test')
    parser.add_argument('-ho', '--home', help='path of the "home" directory that wtperf will use')
    parser.add_argument('-re',
                        '--reuse',
                        action="store_true",
                        help='reuse and reanalyse results from previous tests rather than running tests again')
    parser.add_argument('-g', '--git_root', help='path of the Git working directory')
    parser.add_argument('-i', '--json_info', help='additional test information in a json format string')
    parser.add_argument('-bf', '--batch_file', help='Run all specified configurations for a single test')
    parser.add_argument('-args', '--arguments', help='Additional arguments to pass into wtperf')
    parser.add_argument('-ops', '--operations', help='List of operations to report metrics for')
    parser.add_argument('-v', '--verbose', action="store_true", help='be verbose')
    args = parser.parse_args()

    if args.verbose:
        print('WTPerfPy')
        print('========')
        print("Configuration:")
        print("  WtPerf path:       {}".format(args.wtperf))
        print("  Environment:       {}".format(args.env))
        print("  Test path:         {}".format(args.test))
        print("  Home base:         {}".format(args.home))
        print("  Batch file:        {}".format(args.batch_file))
        print("  Arguments:         {}".format(args.arguments))
        print("  Operations:        {}".format(args.operations))
        print("  Git root:          {}".format(args.git_root))
        print("  Outfile:           {}".format(args.outfile))
        print("  Runmax:            {}".format(args.runmax))
        print("  JSON info          {}".format(args.json_info))
        print("  Reuse results:     {}".format(args.reuse))
        print("  Brief output:      {}".format(args.brief_output))

    if args.wtperf is None:
        sys.exit('The path to the wtperf executable is required')
    if args.test is None:
        sys.exit('The path to the test file is required')
    if args.home is None:
        sys.exit('The path to the "home" directory is required')
    if args.batch_file and not os.path.isfile(args.batch_file):
        sys.exit("batch_file: {} not found!".format(args.batch_file))
    if args.batch_file and (args.arguments or args.operations):
        sys.exit("A batch file (-bf) should not be defined at the same time as -ops or -args")
    if not args.verbose and not args.outfile:
        sys.exit("Enable verbosity (or provide a file path) to dump the stats. "
                 "Try 'python3 wtperf_run.py --help' for more information.")

    return args

def parse_json_args(args: argparse.Namespace) -> Tuple[List[str], List[str], WTPerfConfig, Dict]:
    json_info = json.loads(args.json_info) if args.json_info else {}
    arguments = json.loads(args.arguments) if args.arguments else None
    operations = json.loads(args.operations) if args.operations else None

    config = WTPerfConfig(wtperf_path=args.wtperf,
                          home_dir=args.home,
                          test=args.test,
                          batch_file=args.batch_file,
                          arguments=arguments,
                          operations=operations,
                          environment=args.env,
                          run_max=args.runmax,
                          verbose=args.verbose,
                          git_root=args.git_root,
                          json_info=json_info)

    batch_file_contents = None
    if config.batch_file:
        if args.verbose:
            print("Reading batch file {}".format(config.batch_file))
        with open(config.batch_file, "r") as file:
            batch_file_contents = json.load(file)

    return (arguments, operations, config, batch_file_contents)

def validate_operations(config: WTPerfConfig, batch_file_contents: Dict, operations: List[str]):
    # Check for duplicate operations, and exit if duplicates are found
    # First, construct a list of all operations, including potential duplicates
    all_operations = []
    if config.batch_file:
        for content in batch_file_contents:
            all_operations += content["operations"]
    elif operations:
        all_operations += operations
    # Next, construct a new list with duplicates removed.
    # Converting to a dict and back is a simple way of doing this.
    all_operations_nodups = list(dict.fromkeys(all_operations))
    # Now check if any duplicate operations were removed in the deduplication step.
    if len(all_operations_nodups) != len(all_operations):
        sys.exit("List of all operations ({}) contains duplicates".format(all_operations))

    # Also check that all operations provided have an associated PerfStat.
    all_stat_names = [stat.short_label for stat in PerfStatCollection.all_stats()]
    for oper in all_operations:
        if oper not in all_stat_names:
            sys.exit(f"Provided operation '{oper}' does not match any known PerfStats.\n"
                     f"Possible names are: {sorted(all_stat_names)}")

def run_perf_tests(config: WTPerfConfig, 
                   batch_file_contents: Dict, 
                   args: argparse.Namespace, 
                   arguments: List[str], 
                   operations: List[str]) -> List[PerfStat]:
    reported_stats : List[PerfStat] = []

    if config.batch_file:
        if args.verbose:
            print("Batch tests to run: {}".format(len(batch_file_contents)))
        for content in batch_file_contents:
            index = batch_file_contents.index(content)
            if args.verbose:
                print("Batch test {}: Arguments: {}, Operations: {}".
                        format(index,  content["arguments"], content["operations"]))
                perf_stats = PerfStatCollection(content["operations"])
                if not args.reuse:
                    run_test_wrapper(config=config, index=index, arguments=content["arguments"])
                reported_stats += process_results(config, perf_stats, index=index)
    else:
        perf_stats = PerfStatCollection(operations)
        if not args.reuse:
            run_test_wrapper(config=config, index=0, arguments=arguments)
        reported_stats = process_results(config, perf_stats)

    return reported_stats

def report_results(args: argparse.Namespace, config: WTPerfConfig, reported_stats: List[PerfStat]):
    if args.brief_output:
        if args.verbose:
            print("Brief stats output (Evergreen compatible format):")
        perf_results = brief_perf_stats(config, reported_stats)
    else:
        if args.verbose:
            print("Detailed stats output (Atlas compatible format):")
        perf_results = detailed_perf_stats(config, reported_stats)

    if args.verbose:
        perf_json = json.dumps(perf_results, indent=4, sort_keys=True)
        print("{}".format(perf_json))

    if args.outfile:
        dir_name = os.path.dirname(args.outfile)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        with open(args.outfile, 'w') as outfile:
            json.dump(perf_results, outfile, indent=4, sort_keys=True)

def main():
    args = parse_args()
    (arguments, operations, config, batch_file_contents) = parse_json_args(args=args)
    validate_operations(config=config, batch_file_contents=batch_file_contents, operations=operations)
    reported_stats = run_perf_tests(config=config, 
                                    batch_file_contents=batch_file_contents,
                                    args=args, 
                                    arguments=arguments,
                                    operations=operations)
    report_results(args=args, config=config, reported_stats=reported_stats)

if __name__ == '__main__':
    main()
