from engine.appc.sets import SetClass


def test_set_background_model_records_nif_and_offset():
    s = SetClass()
    s.SetBackgroundModel("data/Models/Sets/StarbaseControl/starbasecontrolRM.nif", 1.0, 2.0, 3.0)
    assert s.GetBackgroundModelNIF() == "data/Models/Sets/StarbaseControl/starbasecontrolRM.nif"
    assert s._background_model[1] == (1.0, 2.0, 3.0)


def test_set_background_model_default_offset_is_origin():
    s = SetClass()
    s.SetBackgroundModel("x.nif")
    assert s._background_model[1] == (0.0, 0.0, 0.0)


def test_get_background_model_nif_none_when_unset():
    assert SetClass().GetBackgroundModelNIF() is None


def test_create_ambient_light_records_clamped_dimmer():
    s = SetClass()
    s.CreateAmbientLight(1.0, 1.0, 1.0, 19.0, "ambientlight1")   # MissionLib outlier
    assert s.GetAmbient() == (1.0, 1.0, 1.0, 1.0)                # clamped to 1.0
