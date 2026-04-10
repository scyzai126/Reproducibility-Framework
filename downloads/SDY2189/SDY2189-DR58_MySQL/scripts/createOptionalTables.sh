#!/bin/bash

if [ $# != 4 ]
  then
    echo ""
    echo "Usage: createOptionalTables.sh Host, User, Password, Database"
    echo ""
    exit 1
fi

HOST=$1
USER=$2
PASSWORD=$3
DATABASE=$4

CMD="mysql --show-warnings -h $HOST -u $USER -p$PASSWORD $DATABASE"

echo "Creating fcs_analyzed_result_marker"
$CMD < ../tables/fcs_analyzed_result_marker.ddl

echo "Creating fcs_header"
$CMD < ../tables/fcs_header.ddl

echo "Creating fcs_header_marker"
$CMD < ../tables/fcs_header_marker.ddl

echo "Creating mass_spectrometry_result"
$CMD < ../tables/mass_spectrometry_result.ddl

