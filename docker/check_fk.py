import json
from pathlib import Path
import numpy as np
import pinocchio as pin
from franka_platform.kinematics import UrdfFK
from franka_platform.transforms import rotate
obs=json.loads(Path('/run/franka/observation.json').read_text())
base,tool=obs['tcp_pose']['base_frame'],obs['tcp_pose']['tool_frame']
names=obs['joint_names']
model=pin.buildModelFromUrdf('/run/franka/robot.urdf')
assert model.existFrame(base) and model.existFrame(tool)
fk=UrdfFK('/run/franka/robot.urdf',base,tool,names)
positions=[obs['positions_rad'],[0.]*7,[v+.01 for v in obs['positions_rad']]]
max_p=max_r=0.
for joints in positions:
    q=pin.neutral(model)
    for name,value in zip(names,joints):
        assert model.existJointName(name)
        joint=model.joints[model.getJointId(name)]
        assert joint.nq==1
        q[joint.idx_q]=value
    data=model.createData()
    pin.framesForwardKinematics(model,data,q)
    pose=data.oMf[model.getFrameId(base)].inverse()*data.oMf[model.getFrameId(tool)]
    actual=fk.pose(joints)
    rotation=np.column_stack([rotate(actual['quaternion_xyzw'],axis) for axis in np.eye(3)])
    max_p=max(max_p,float(np.max(np.abs(np.array(actual['position_m'])-pose.translation))))
    max_r=max(max_r,float(np.max(np.abs(rotation-pose.rotation))))
assert max_p<1e-10 and max_r<1e-10
print(json.dumps({'status':'PASS','pinocchio_version':pin.__version__,'poses_checked':len(positions),
 'maximum_position_difference_m':max_p,'maximum_rotation_matrix_difference':max_r,
 'network':'none','actuator_writes':0,'note':'Actual local URDF; measured and mathematical positions; no joint samples published'},indent=2))
