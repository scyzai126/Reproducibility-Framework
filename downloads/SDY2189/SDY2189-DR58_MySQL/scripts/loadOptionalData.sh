#!/bin/bash

if [ $# != 4 ]
  then
    echo ""
    echo "Usage: loadOptionalData.sh Host, User, Password, Database"
    echo ""
    exit 1
fi

HOST=$1
USER=$2
PASSWORD=$3
DATABASE=$4

CMD="mysql --local_infile --show-warnings -h $HOST -u $USER -p$PASSWORD $DATABASE"

echo "Loading fcs_analyzed_result_marker"
$CMD < ../load/fcs_analyzed_result_marker.load

echo "Loading fcs_header"
$CMD < ../load/fcs_header.load

echo "Loading fcs_header_marker"
$CMD < ../load/fcs_header_marker.load

echo "Loading mass_spectrometry_result"
$CMD < ../load/mass_spectrometry_result.load
