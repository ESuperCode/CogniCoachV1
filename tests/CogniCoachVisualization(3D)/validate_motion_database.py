"""Validate every motion in motion_database.py: compiles it alone (upper-body motions on a stance) and
reports arm/body penetration and abrupt joint speed changes.  python validate_motion_database.py"""
import sys
import motion_database as db
import motion_script as ms

LOWER = {"right_leg", "left_leg"}


def check(name: str):
    m = db.DB[name]
    owned = set(m["parts"]) | set(m["soft_parts"])
    script = name if owned & LOWER or "body" in owned else f"stance(depth=0.3) + {name}"
    if m["kind"] == "cycle":
        script = name.replace(name, f"{name}(times=2)") if script == name else f"stance(depth=0.3) + {name}(times=2)"
    r = ms.compile_script(script, db.DB)
    return script, r["report"]


if __name__ == "__main__":
    bad = 0
    for name in (sys.argv[1:] or db.DB):
        script, rep = check(name)
        flag = "OK " if not rep["issues"] else "FIX"
        bad += bool(rep["issues"])
        print(f"{flag} {name:20s} pen {rep['max_arm_penetration_m']*100:4.1f} cm  accel {rep['max_joint_step_m']:.2f}  {'; '.join(rep['issues'])}")
    print(f"{len(sys.argv[1:]) or len(db.DB)} motions, {bad} need attention")
