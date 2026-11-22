import zm_triad

def test():
    t1 = zm_triad.build_zm138_triad("Modect")
    assert t1["Function"] == "Modect"
    assert t1["Capturing"] == "Always"
    assert t1["Analysing"] == "Always"
    assert t1["Recording"] == "OnMotion"
    assert t1["Enabled"] == "1"

    t2 = zm_triad.build_zm138_triad("None")
    assert t2["Function"] == "None"
    assert t2["Capturing"] == "None"
    assert t2["Analysing"] == "None"
    assert t2["Recording"] == "None"
    assert t2["Enabled"] == "0"

    t3 = zm_triad.build_zm138_triad(capturing="Always", analysing="Always", recording="Always")
    assert t3["Function"] == "Mocord"
    assert t3["Capturing"] == "Always"
    assert t3["Analysing"] == "Always"
    assert t3["Recording"] == "Always"
    assert t3["Enabled"] == "1"

    t4 = zm_triad.build_zm138_triad(capturing="None")
    assert t4["Function"] == "None"
    assert t4["Capturing"] == "None"
    assert t4["Analysing"] == "None"
    assert t4["Recording"] == "None"
    assert t4["Enabled"] == "0"

    p1 = zm_triad.zm138_monitor_payload(t1)
    assert p1["Monitor[Function]"] == "Modect"
    assert p1["Monitor[Capturing]"] == "Always"
    assert p1["Monitor[Analysing]"] == "Always"
    assert p1["Monitor[Recording]"] == "OnMotion"
    assert p1["Monitor[Enabled]"] == "1"
    assert p1["Monitor[Device]"] == ""

    print("ALL TESTS PASSED in zm_triad.py!")

if __name__ == "__main__":
    test()

