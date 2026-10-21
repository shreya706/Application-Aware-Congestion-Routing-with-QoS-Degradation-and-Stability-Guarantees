import unittest
from policy import FlowState, route_decision


class StabilityTests(unittest.TestCase):
    def test_three_intervals_and_cooldown(self):
        state=FlowState((1,2,4,5),last_change=0)
        args=dict(current_score=.5,proposed_score=.8,improvement=.15,stable_intervals=3,cooldown=5)
        self.assertEqual(route_decision(state,(1,3,4,5),now=5,**args)[0],"KEEP")
        self.assertEqual(route_decision(state,(1,3,4,5),now=6,**args)[0],"KEEP")
        self.assertEqual(route_decision(state,(1,3,4,5),now=7,**args)[0],"REROUTE")
    def test_recent_reversal_requires_more_gain(self):
        state=FlowState((1,2,5)); state.previous_paths.append(((1,3,5),10))
        decision,_=route_decision(state,(1,3,5),.5,.65,now=20,improvement=.15,stable_intervals=1,cooldown=0,memory_seconds=20,reversal_penalty=.2)
        self.assertEqual(decision,"KEEP")


if __name__=="__main__": unittest.main()
