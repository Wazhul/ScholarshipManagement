async function main() {
    const ScholarshipManager = await ethers.getContractFactory("ScholarshipManager");
    const scholarshipManager = await ScholarshipManager.deploy();
  
    await scholarshipManager.waitForDeployment();
    
    console.log("ScholarshipManager deployed to:", await scholarshipManager.getAddress());
  }
  
  main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });