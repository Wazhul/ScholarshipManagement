// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

contract ScholarshipManager {
    struct ScholarshipRecord {
        string uniqueId;
        bool eligible;
        uint256 timestamp;
        address institution;
        uint256 scholarshipAmount;
        string rejectionReason;
    }

    struct ScholarshipProgram {
        string id;
        string name;
        uint256 amount;
        address institution;
        bool active;
    }

    mapping(string => ScholarshipRecord) public records;
    mapping(string => ScholarshipProgram) public scholarshipPrograms;
    mapping(address => bool) public authorizedInstitutions;

    event ScholarshipRecorded(
        string indexed uniqueId,
        bool eligible,
        uint256 amount,
        string reason
    );
    
    event ProgramCreated(
        string indexed programId,
        address indexed institution,
        uint256 amount
    );

    modifier onlyInstitution() {
        require(authorizedInstitutions[msg.sender], "Not authorized institution");
        _;
    }

    function createScholarshipProgram(
        string memory programId,
        string memory name,
        uint256 amount
    ) external onlyInstitution {
        scholarshipPrograms[programId] = ScholarshipProgram({
            id: programId,
            name: name,
            amount: amount,
            institution: msg.sender,
            active: true
        });
        emit ProgramCreated(programId, msg.sender, amount);
    }

    function recordScholarship(
        string memory uniqueId,
        bool eligible,
        uint256 amount,
        string memory rejectionReason
    ) external onlyInstitution {
        records[uniqueId] = ScholarshipRecord({
            uniqueId: uniqueId,
            eligible: eligible,
            timestamp: block.timestamp,
            institution: msg.sender,
            scholarshipAmount: amount,
            rejectionReason: rejectionReason
        });
        
        emit ScholarshipRecorded(uniqueId, eligible, amount, rejectionReason);
    }

    function getScholarshipRecord(string memory uniqueId)
        public
        view
        returns (
            string memory,
            bool,
            uint256,
            address,
            uint256,
            string memory
        )
    {
        ScholarshipRecord memory record = records[uniqueId];
        return (
            record.uniqueId,
            record.eligible,
            record.timestamp,
            record.institution,
            record.scholarshipAmount,
            record.rejectionReason
        );
    }

    function authorizeInstitution(address institution) external {
        // Add access control as needed (e.g., onlyOwner)
        authorizedInstitutions[institution] = true;
    }
}