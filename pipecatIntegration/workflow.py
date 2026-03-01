from loguru import logger


class BaseWorkflow:
    def __init__(self, agent_workflow):
        self.agent_workflow = agent_workflow
        self.current_workflow = None
        self.current_node = None
        self.next_node_name = None
        self.current_nodes_name_list = []

    def choose_scenario(self, scenario_name):
        workflows = self.agent_workflow.get("workflows", {})

        if scenario_name not in workflows:
            available = ", ".join(workflows.keys())
            return (
                f"{scenario_name} not available, available Scenarios are {available}. "
                "Based on the user intent please choose one of the available Scenarios"
            )

        self.current_workflow = workflows[scenario_name]
        self.current_nodes_name_list = list(self.current_workflow["nodes"].keys())
        current_node_name = self.current_nodes_name_list[0]
        self.next_node_name = (
            self.current_nodes_name_list[1]
            if len(self.current_nodes_name_list) > 1
            else ""
        )
        self.current_node = self.current_workflow["nodes"][current_node_name]

        logger.info(f"Scenario selected: {scenario_name}")
        return self.current_node["prompt"]

    def get_workflows(self):
        return "\n".join(
            f"{key} - {self.agent_workflow["workflows"][key]["description"]}"
            for key in self.agent_workflow["workflows"].keys()
        )
