
export class BaseWorkflow {
  constructor(agentWorkflow) {
    this.agentWorkflow = agentWorkflow;
    this.currentWorkflow = null;
    this.currentNode = null;
    this.nextNodeName = null;
    this.currentNodesNameList = [];
  }

  chooseScenario({ scenarioName }) {
    const workflowName = scenarioName;
    if (!this.agentWorkflow.workflows[workflowName]) {
      return `${workflowName} not available, available Scenarios are ${Object.keys(
        this.agentWorkflow.workflows,
      ).join(
        ", ",
      )} Based on the user intent please choose one of the available Scenarios`;
    }

    this.currentWorkflow = this.agentWorkflow.workflows[workflowName];

    this.currentNodesNameList = Object.keys(this.currentWorkflow.nodes);

    this.currentNodeName = this.currentNodesNameList[0];

    this.nextNodeName = this.currentNodesNameList[1] || "";

    this.currentNode = this.currentWorkflow.nodes[this.currentNodeName];

    return this.currentNode.prompt;
  }
}
