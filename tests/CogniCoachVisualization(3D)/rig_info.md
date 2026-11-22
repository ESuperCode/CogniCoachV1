* Center of mass(0,0,0)
  * HipJoint(0,0,0)

    * Pelvis(20,10,10)
    * LeftHipJoint(-6,-0.6,0)

      * LeftFemur(7.5,17.25,10)(0,-8.75,0)
      * LeftKneeJoint(0,-1.75,0)

        * LeftTibia(7.5,15.4,7.5)(0,-7.7,0)
    * RightHipJoint(6,-0.6,0,0)

      * RightFemur(7.5,17.5,10)(0,-8.75,0)
      * RightKneeJoint(0,-1.75,0)

        * RightTibia(7.5,15.4,7.5)(0,-7.7,0)
  * SpineBaseJoint(0,0,0)

    * Torso(20,30,10)(0,15,0)
    * RightShoulderJoint(-13,22,0)

      * UpperRightArm(7.5,20,7.5)(0,-0.5,0)
      * RightElbowJoint(0,-1,0)

        * LowerRightArm(7.5,20,7.5)(0,-10,0)
    * LeftShoulderJoint(-13,22,0)

      * UpperLeftArm(7.5,20,7.5)(0,-0.5,0)
      * LeftElbowJoint(0,-1,0)

        * LowerLeftArm(7.5,20,7.5)(0,-10,0)
  * NeckJoint(0,30,0)

    * Head(12,16,15)(0,8,0)
How to read this schema:
All objects are arranged in this hierarchy in the unity game. All joints are not actual objects but instead empty objects just used to rotate limbs around certain points. For the non joint object(the actual limb objects) there are two sets of three values the first set is is the dimensions of the object(x_width,y_height,z_length) basically its just the scale values set in unity, and for the second set of three values, they are the x,y,z position values, so the center of mass is at (0,0,0). The joint objects also have xyz coordinates which are the positions (X,y,z). The limb position coordinates are mostly just -1/2 * height which means that they are connected to the joint at the absolute top, there are also ones like the neck where it is 1/2 * height because it is connected at the absolute bottom, the reason I put this value is because some of them aren't perfectly aligned like that for example the shoulders.

## Motion engine contract

`motion_engine.py` uses these proportions (measured against the Unity WebGL build) for its
kinematics; `GET /rig` returns them. The language model never writes joint angles, coordinates or
movement data, and the engine has no pre-programmed movements: the model describes each beat of a
movement with enum-only spatial descriptors (see `motion_grammar.py`) - hand height x direction x
reach x elbow, foot position x height x leg shape, support base, hip level, trunk, facing, timing
and which limbs perform the skill - and the
engine computes the targets, infers supporting biomechanics, solves the joints and emits local
Unity Euler angles (Z-X-Y) per joint in the sparse frame format consumed by `RagdollTest_AI.html`.
`positionx/y/z` carry whole-body rotation and `rooty` the vertical root offset in metres.
