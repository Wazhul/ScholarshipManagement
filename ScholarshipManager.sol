// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract ScholarshipManager {
    // Structure to hold scholarship record for a student
    struct ScholarshipRecord {
        string uniqueId;
        bool eligible;
    }
    
    // Mapping from unique student ID to their scholarship record
    mapping(string => ScholarshipRecord) public records;
    
    // Event emitted when a scholarship record is added or updated
    event ScholarshipRecorded(string uniqueId, bool eligible);
    
    // Function to record scholarship eligibility on the blockchain
    function recordScholarship(string memory uniqueId, bool eligible) public {
        records[uniqueId] = ScholarshipRecord(uniqueId, eligible);
        emit ScholarshipRecorded(uniqueId, eligible);
    }
    
    // Function to retrieve a student's scholarship record
    function getScholarshipRecord(string memory uniqueId) public view returns (string memory, bool) {
        ScholarshipRecord memory record = records[uniqueId];
        return (record.uniqueId, record.eligible);
    }
}
