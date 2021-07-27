#!/usr/bin/env python3.9

"""Provides a safe and reliable tool to backup a directory of files from android to a local computer.
Supports nested directories."""

import argparse
import re
import subprocess
import os
import sys
import shlex
import hashlib
from tqdm import tqdm


# utility functions

def sha1sum(filename):
    """Returns 'sha1sum filename'"""
    h = hashlib.sha1()
    b = bytearray(128*1024)
    mv = memoryview(b)
    with open(filename, 'rb', buffering=0) as f:
        for n in iter(lambda: f.readinto(mv), 0):
            h.update(mv[:n])
    return h.hexdigest()


def print_error(msg):
    """Prints msg to stderr"""
    print(msg, file=sys.stderr)


def linux_path_build(*args):
    """As os.path.join on linux (implemented for compatibility with windows)."""
    return '/'.join(args)


def ask_user_yes_no(msg):
    """Asks a user a question with 'yes/no' options. Returns True for yes, False otherwise"""
    return bool(re.match('^y(es)?$', input(f'{msg} y(es)/n(o) ').lower()))


def truncate_list(lst, truncate_size=20):
    """Replaces lists/tuples longer then truncate_size with a list with truncate_size members plus a string
    '... (total: {len(lst)}' and returns the truncated copy."""
    if len(lst) > truncate_size:
        lst_len = len(lst)
        lst = lst[:truncate_size]
        lst.append(f'... (total: {lst_len})')
    return lst


def filename2osformat(f):
    """Gets a filename, may be with a relative path. Converts the relative path to the local OS format."""
    return f.replace('/', os.path.sep)


def filename2linuxformat(f):
    """Gets a filename, may be with a relative path. Converts the relative path to linux format."""
    return f.replace(os.path.sep, '/')


# local operations function

def get_dst_sha1sum(dst_path, f):
    """Returns from the android 'sha1sum file'"""
    full_path = os.path.join(dst_path, filename2osformat(f))
    return sha1sum(full_path)


def create_all_directories(path, dirs):
    """Safely create directories in 'path', if they don't exist. Creates intermediate directories if needed."""
    # now we should get parent directories before child directories in list.
    # Nevertheless, for any case, we use makedirs which creates non-existing intermediate directories.
    dirs.sort()
    for d in dirs:
        full_path = os.path.join(path, filename2osformat(d))
        if not os.path.exists(full_path):
            os.makedirs(full_path, exist_ok=True)
        elif not os.path.isdir(full_path):
            raise TypeError(f'A path to a need-to-be directory exists as a file. Aborting...\n{full_path}')


def delete_files(dst_path, files):
    """Delete the specified files in dst_path."""
    if isinstance(files, str):
        files = [files]
    for f in files:
        os.remove(os.path.join(dst_path, filename2osformat(f)))


def get_dst_all_files_and_dirs(dst_path):
    """Returns two complete recursive lists of files, dirs in dst_path."""
    # immediate files and dirs lists
    items = os.listdir(dst_path)
    files = [f for f in items if os.path.isfile(os.path.join(dst_path, filename2osformat(f)))]
    dirs = [f for f in items if os.path.isdir(os.path.join(dst_path, filename2osformat(f)))]

    # find recursively inner files and dirs
    for d in dirs:
        new_files, new_dirs = get_dst_all_files_and_dirs(os.path.join(dst_path, filename2osformat(d)))
        files.extend([os.path.join(d, filename2osformat(nf)) for nf in new_files])
        dirs.extend([os.path.join(d, filename2osformat(nf)) for nf in new_dirs])

    return files, dirs


# android interaction functions

def run(cmd):
    """Runs a command, splits cmd to arguments as required, decodes as utf8, removing all '\r\r's and strips."""
    args_list = shlex.split(cmd)
    return subprocess.check_output(args_list).decode('utf8').replace('\r\r', '').strip()


def get_src_path_type(adb_path, src_path):
    """Checks what is the type of src_path. Returns 'directory', 'file' or 'none' in case of either of those."""
    return run(f'"{adb_path}" shell "test -f \'{src_path}\' && echo file || '
               f'(test -d {src_path} && echo directory || echo none )"')


def get_src_all_files_and_dirs(adb_path, src_path):
    """Returns a list of the files and a list of the directories in src_path."""
    files = run(f'"{adb_path}" shell "cd \'{src_path}\';find -L . -type f | '
                f'sed \'s/^\\.\\/\\(.*\\)/\\1/g\'"').splitlines()
    directories = run(f'"{adb_path}" shell "cd \'{src_path}\'; find -L . -type d | '
                      f'grep -v \'^\\.$\' | sed \'s/^\\.\\/\\(.*\\)/\\1/g\'"').splitlines()

    return files, directories


def get_src_file_size(adb_path, src_path, f):
    """Returns the size of the file in bytes (as an integer)"""
    full_path = linux_path_build(src_path, f)
    return int(run(f'"{adb_path}" shell "stat -c %s \'{full_path}\' | cut -f1"'))


def get_src_sha1sum(adb_path, src_path, f):
    """Returns the result of sha1sum <f>"""
    full_path = linux_path_build(src_path, f)
    return run(f'"{adb_path}" shell "sha1sum \'{full_path}\' | cut -d\' \' -f1"')


def pull_file(adb_path, src_path, dst_path, f):
    """Pulls a file f from src_path to dst_path.
       If pulled successfully, returns 'success'.
       If fails to pull, to pull completely or to pull correctly, returns 'not_pulled, 'wrong_size' and 'wrong_hash',
       accordingly."""
    full_src_path = linux_path_build(src_path, f)
    full_dst_path = os.path.join(dst_path, filename2osformat(f))
    run(f'"{adb_path}" pull "{full_src_path}" "{os.path.dirname(full_dst_path)}"')

    # was pulled?
    if not os.path.isfile(full_dst_path):
        if os.path.exists(full_dst_path):
            raise('A supposed to be file exists as a directory. This issue should have been discovered earlier, '
                  'this is a bug...'
                  'file=%s' % full_dst_path)
        return 'not_pulled'
    # was pulled completely?
    if get_src_file_size(adb_path, src_path, f) != os.path.getsize(full_dst_path):
        return 'wrong_size'
    # was pulled correctly?
    if get_src_sha1sum(adb_path, src_path, f) != get_dst_sha1sum(dst_path, f):
        return 'wrong_hash'

    return 'success'


# comparison functions

def get_missing_and_existing_files(adb_path, src_path, dst_path):
    """Finds which files and directories in src are missing in dst.
    Returns missing files, existing files, missing directories, existing directories"""
    # get local files and dirs. Converts them to linux format for comparison.
    # convert all lists to sets for easier comparisons.
    src_files, src_dirs = [set(lst) for lst in get_src_all_files_and_dirs(adb_path, src_path)]
    dst_files, dst_dirs = [set([filename2linuxformat(f) for f in lst]) for lst in get_dst_all_files_and_dirs(dst_path)]

    missing_files = list(src_files - dst_files)
    existing_files = list(src_files.intersection(dst_files))
    missing_dirs = list(src_dirs - dst_dirs)
    existing_dirs = list(src_dirs.intersection(dst_dirs))

    # make sure there arent any files that should be directory or vice versa
    bad_type_items = (set(existing_files).intersection(set(missing_dirs))
                      | set(missing_files).intersection(set(existing_dirs)))
    if bad_type_items:
        raise TypeError('The following files/dirs should be dirs/files:\n\t%s' %
                        '\n\t'.join(sorted(list(bad_type_items))))

    return missing_files, existing_files, missing_dirs, existing_dirs


def verify(adb_path, src_path, dst_path, existing_files):
    """Verifies which of the existing files in dst are identical to the ones in src."""
    # get sha1sums
    src_sha1sum = {f: get_src_sha1sum(adb_path, src_path, f)
                   for f in tqdm(existing_files, desc='Hashing android files')}
    dst_sha1sums = {f: get_dst_sha1sum(dst_path, f) for f in tqdm(existing_files, desc='Hashing local files')}
    # get file sizes, just in case
    src_file_sizes = {f: get_src_file_size(adb_path, src_path, f)
                      for f in tqdm(existing_files, desc='Getting android files sizes')}
    dst_file_sizes = {f: os.path.getsize(os.path.join(dst_path, filename2osformat(f)))
                      for f in tqdm(existing_files, desc='Getting local files sizes')}

    # filter files that don't match in sha1sum or in size
    faulty_files = [f for f in existing_files
                    if (src_sha1sum[f] != dst_sha1sums[f]) or (src_file_sizes[f] != dst_file_sizes[f])]

    return faulty_files


def main(src_path=None, dst_path=None, print_filename_prefix=''):
    # parse cmdline
    parser = argparse.ArgumentParser(description="Backups a directory from the android device to the computer with ADB."
                                                 "\nIt's recommended that partial backups will be validated before"
                                                 "continued.\n"
                                                 "Doesn't support recursive directories (supports only directories that"
                                                 "contain files only).")
    parser.add_argument('src_path', metavar='android_source_path', type=str, help='path to the backed directory')
    parser.add_argument('dst_path', metavar='destination_path', type=str, help='path to the destination directory')
    parser.add_argument('-o', '--override', action='store_true', help='override existing files')
    parser.add_argument('-v', '--verify', action='store_true', help='verify backup')
    parser.add_argument('-a', '--auto', action='store_true', help='automatically verify, delete faulty backups and '
                                                                  'continue the backup')
    parser.add_argument('--adb-path', action='store', type=str, help='path to ADB, if it is not in path')
    parser.add_argument('-y', '--yes', action='store_true', help='automatically approve deletions of faulty backups '
                                                                 'or override')

    args = parser.parse_args()
    src_path = src_path if src_path else args.src_path
    dst_path = dst_path if dst_path else args.dst_path
    # sets the adb path
    adb_path = 'adb'
    if args.adb_path:
        adb_path = args.adb_path

    # validates that all inputs are valid, exist etc
    if not os.path.isfile(adb_path):
        print_error('Bad ADB path.')
        return
    if not os.path.isdir(dst_path):
        print_error('Bad destination path.')
        return
    devices_output = run(f'"{adb_path}" devices')
    if not any(re.findall(r'^[a-z0-9]+\s+device$', devices_output, flags=re.M)):
        print_error('Phone not connected.')
        return
    # src_type will be 'file', 'directory' or 'none'
    src_type = get_src_path_type(adb_path, src_path)

    # get lists of missing/existing files/directories
    if src_type == 'none':
        print_error("Source path on android doesn't exist")
        return
    elif src_type == 'file':
        missing_files, existing_files, missing_dirs, existing_dirs = [], [], [], []
        # get the filename and separate it from the path for later use
        filename = os.path.basename(src_path)
        src_path = os.path.dirname(src_path)
        # path to the file on the local machine, if exists
        local_file_path = os.path.join(dst_path, filename2osformat(filename))
        # check if file exists, and if so verify it's not a directory
        if os.path.exists(local_file_path):
            if not os.path.isfile(local_file_path):
                raise TypeError(f'{local_file_path} should be a file, but it is a directory. Aborting...')
            existing_files.append(filename)
        else:
            missing_files.append(filename)
    else:
        # find which files and directories exist
        missing_files, existing_files, missing_dirs, existing_dirs = get_missing_and_existing_files(adb_path, src_path,
                                                                                                    dst_path)

    # print the missing results
    print(f'Missing files:\n\t%s' % ('\n\t'.join(truncate_list(missing_files)) if missing_files else 'None'))
    print(f'Missing dirs:\n\t%s' % ('\n\t'.join(truncate_list(missing_dirs)) if missing_dirs else 'None'))
    create_all_directories(dst_path, missing_dirs)

    # if verification of existing backup is required
    if args.verify or args.auto:
        print("Checking for faulty files.")
        bad_files = verify(adb_path, src_path, dst_path, existing_files)
        print('Faulty backed files:\n\t%s' % ('\n\t'.join(truncate_list(bad_files)) if bad_files else 'None'))
        # ask user and delete faulty files
        if bad_files and (args.yes or ask_user_yes_no('Delete files?')):
            print('Deleting faulty files...')
            delete_files(dst_path, bad_files)
        missing_files.extend(bad_files)
        existing_files = list(set(existing_files) - set(bad_files))
        # if only verification was required, stop here
        if args.verify:
            return

    # if override chosen, verify with user and replace the pulling list to all the files
    if args.override:
        if args.yes or ask_user_yes_no('Confirm overriding.'):
            print('Overriding...')
            missing_files.extend(existing_files)

    # Pull the missing files
    failed_files = []
    if missing_files:
        print('Estimating missing files total size.')
        src_file_sizes = {f: get_src_file_size(adb_path, src_path, f)
                          for f in tqdm(missing_files, desc='Getting android missing files sizes')}
        total_missing_size = sum(src_file_sizes.values())
        print('%.2fMB of missing files will be pulled.' % (total_missing_size/1024**2))
        print('\nPulling missing files.')
        with tqdm(total=total_missing_size, unit='B', unit_scale=True, desc='Pulling progress') as progressbar:
            for f in missing_files:
                progressbar.set_postfix_str(f)
                pull_status = pull_file(adb_path, src_path, dst_path, f)
                if pull_status != 'success':
                    print_error(f'\nError while pulling {print_filename_prefix + f}. Error: {pull_status}.%s' %
                                (' Deleting...' if pull_status != 'not_pulled' else ''))
                    failed_files.append(f)
                    if pull_status != 'not_pulled':
                        delete_files(dst_path, f)
                progressbar.update(src_file_sizes[f])
    num_of_failed_pulls = len(failed_files)
    num_of_successful_pulls = len(missing_files) - num_of_failed_pulls

    # print results
    newline_tab_str = "\n\t"
    print('\n')
    print(f'Pulled successfully {num_of_successful_pulls} files.\n'
          f'Failed to pull {num_of_failed_pulls} files', end='')
    # print 'Failed to pull 0.' or 'Failed to pull 1953: <list of files>'
    if num_of_failed_pulls:
        print(f':\n\t{newline_tab_str.join(failed_files)}')
    else:
        print('.')


if __name__ == '__main__':
    main()
