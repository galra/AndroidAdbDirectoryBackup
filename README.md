## What is this?

This is a small script to provide safe backup of directories and files from an android device to a local computer. It also provides partial functionality such as verification of the validity of a current backup (both missing files, and that the backed files are valid).

## What verifications are applied?

1. Missing files and folders are recognized and set aside for a backup, unless only verification was asked. 
   
2. When asked to verify existing backup, or when verifying new backed files during a backup, the files are:
   
   (a) verified to exist.
   
   (b) verified to  have the same sizes.

   (c) verified to have the same sha1sum hash

Files that fail to meet any of the above criteria are announced to be found invalid/failed to be backed.


## Support platforms
It should work on any android that supports adb (usb debugging), and on any system supported by python and adb.

It was tested on Win10 with Galaxy S7 (android 6.0.1), with python 3.9.1 and adb 1.0.39.

## Requirements 
* adb
* python (probably 3.6 and higher)
* packages as detailed in requirements.txt

## How to run
Just connect the phone to the computer, make sure adb can communicate with it (requires to enable usb debugging on the phone, [see here](https://developer.android.com/studio/debug/dev-options)).

Now you can simply run the script with no arguments and follow the instructions. If adb isn't in the system path, the path to it should be specified.