#!/bin/bash

#
# This script combines all the step to create tables,
# indexes, foreign keys and load the data into new database
#
# This script depends on the Enviroment variables configure
# in the ".env" file.
#
# Example of exposing the environment variables
# set -o allexport && source .env && set +o allexport
#

#
# Remove previous log files
#
rm ${DATA_RELEASE_DIRECTORY}/logs/createLkSchema.log
rm ${DATA_RELEASE_DIRECTORY}/logs/loadLkData.log
rm ${DATA_RELEASE_DIRECTORY}/logs/createResearchTables.log
rm ${DATA_RELEASE_DIRECTORY}/logs/createResearchIndexes.log
rm ${DATA_RELEASE_DIRECTORY}/logs/createForeignKeys.log
rm ${DATA_RELEASE_DIRECTORY}/logs/loadResearchDataTopDown.log

echo "createLkSchema"
time createLkSchema.sh $DB_SERVER $DB_USER $DB_PASSWORD $DB_DATABASE >${DATA_RELEASE_DIRECTORY}/logs/createLkSchema.log 2>&1
echo ""
echo ""
echo "loadLkData"
time loadLkData.sh $DB_SERVER $DB_USER $DB_PASSWORD $DB_DATABASE > ${DATA_RELEASE_DIRECTORY}/logs/loadLkData.log 2>&1
echo ""
echo ""
echo "createResearchTables"
time createResearchTables.sh $DB_SERVER $DB_USER $DB_PASSWORD $DB_DATABASE > ${DATA_RELEASE_DIRECTORY}/logs/createResearchTables.log 2>&1
echo ""
echo ""
echo "createResearchIndexes"
time createResearchIndexes.sh $DB_SERVER $DB_USER $DB_PASSWORD $DB_DATABASE > ${DATA_RELEASE_DIRECTORY}/logs/createResearchIndexes.log 2>&1
echo ""
echo ""
echo "createForeignKeys"
time createForeignKeys.sh $DB_SERVER $DB_USER $DB_PASSWORD $DB_DATABASE > ${DATA_RELEASE_DIRECTORY}/logs/createForeignKeys.log 2>&1
echo ""
echo ""
echo "loadResearchDataTopDown"
time loadResearchDataTopDown.sh $DB_SERVER $DB_USER $DB_PASSWORD $DB_DATABASE > ${DATA_RELEASE_DIRECTORY}/logs/loadResearchDataTopDown.log 2>&1
echo ""
echo ""
