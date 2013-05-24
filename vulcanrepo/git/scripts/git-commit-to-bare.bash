#!/bin/bash -x

set -e

# --- settings ---
MIN_ARGS=8
STEP_TOTAL=8
# ----------------
MY_NAME=`basename $0`
# ----------------
	
function show_help {
cat <<_EOF_

SCRIPT:
    $MY_NAME

DESCRIPTION:
    A workflow to commit to a --bare git repository by creating a sparse 
    checkout and committing a new file as a specified user.

USAGE:
    $MY_NAME [options] SOURCE BRANCH_OR_REF DEST USERNAME EMAIL FILE_SOURCE FILE_DEST COMMIT_MESSAGE

OPTIONS:
    -h --help       show help and exit
    -t --test       run a test
_EOF_
}

function error {
echo >&2
echo "ERROR:" >&2
echo "    $2" >&2
show_help >&2
exit $1
}

# from: http://superuser.com/questions/205127/how-to-retrieve-the-absolute-path-of-an-arbitrary-file-from-the-os-x
function abspath() { pushd . > /dev/null; if [ -d "$1" ]; then cd "$1"; dirs -l +0; else cd "`dirname \"$1\"`"; cur_dir=`dirs -l +0`; if [ "$cur_dir" == "/" ]; then echo "$cur_dir`basename \"$1\"`"; else echo "$cur_dir/`basename \"$1\"`"; fi; fi; popd > /dev/null; }

STEP_COUNTER=0
function printstep {
let "STEP_COUNTER += 1"
echo "[${STEP_COUNTER}/${STEP_TOTAL}] $1"
}

function indented {
while read data
do
sed 's/^/    /g'
done
}

# parse option flags
case "$1" in

-h )
show_help
exit 0
;;

--help )
show_help
exit 0
;;

-t )
echo "cleaning up from last test..."
rm -rf tmp_firetracks-code
cat <<_EOF_
running test command which expects some local files and repos to exist...
_EOF_
echo
echo "test" >> test_dir/test.txt
$0 firetracks-code.git master tmp_firetracks-code \
curly "curly@stooge.com" \
test_dir some_directory/test_dir \
'Somebody just committed something to a bare repo!'
exit 0
;;

esac

# validate number of arguments
if [[ $# -lt $MIN_ARGS ]]
then
	error 1 "Not enough arguments. Minimum: ${MIN_ARGS}"
fi

# parse args
SOURCE=`abspath $1`
BRANCH_OR_REF=$2
DEST=`abspath $3`
USERNAME=$4
EMAIL=$5
FILE_SOURCE=$6
FILE_DEST=$7
COMMIT_MESSAGE=$8
#
ABS_FILE_SOURCE=`abspath $FILE_SOURCE`
ABS_FILE_DEST="${DEST}/${FILE_DEST}"

echo "running ${MY_NAME} with:"
echo "    SOURCE: $SOURCE"
echo "    BRANCH_OR_REF: $BRANCH_OR_REF"
echo "    DEST: $DEST"
echo "    USERNAME: $USERNAME"
echo "    EMAIL: $EMAIL"
echo "    FILE_SOURCE: $FILE_SOURCE"
echo "    FILE_DEST: $FILE_DEST"
echo "    COMMIT_MESSAGE: $COMMIT_MESSAGE"
echo "and these computed values:"
echo "    ABS_FILE_SOURCE: $ABS_FILE_SOURCE"
echo "    ABS_FILE_DEST: $ABS_FILE_DEST"
echo

# do stuff

printstep "cloning ${SOURCE} into ${DEST}"
git clone --no-checkout $SOURCE $DEST
pushd $DEST
sleep 1

printstep "setting up git as ${USERNAME}"
git config user.name "${USERNAME}"
git config user.email "${EMAIL}"

printstep "setting up sparse checkout including ${FILE_DEST}"
git config core.sparseCheckout true
dirname $FILE_DEST >> .git/info/sparse-checkout
echo $FILE_DEST >> .git/info/sparse-checkout

printstep "checking out ${BRANCH_OR_REF}"
git checkout $BRANCH_OR_REF

printstep "copying ${ABS_FILE_SOURCE} to ${ABS_FILE_DEST}"
mkdir -p `dirname ${ABS_FILE_DEST}`
cp -R $ABS_FILE_SOURCE $ABS_FILE_DEST

printstep "committing"
git add $FILE_DEST
git commit -m "${COMMIT_MESSAGE}"

printstep "pushing"
git push origin $BRANCH_OR_REF

printstep "cleaning up"
popd
rm -rf $DEST

echo "done."

exit
