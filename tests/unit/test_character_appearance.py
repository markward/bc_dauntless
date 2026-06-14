from engine.appc.characters import CharacterClass_Create


def test_appearance_captures_nifs_and_textures_separately():
    c = CharacterClass_Create("Bodies/BodyFemM/BodyFemM.nif",
                              "Heads/HeadLiu/liu_head.nif")
    c.ReplaceBodyAndHead("Bodies/BodyFemS/FedFemRed_body.tga",
                         "Heads/HeadLiu/liu_head.tga")
    ap = c.appearance()
    assert ap["body_nif"] == "Bodies/BodyFemM/BodyFemM.nif"
    assert ap["head_nif"] == "Heads/HeadLiu/liu_head.nif"
    assert ap["body_tex"] == "Bodies/BodyFemS/FedFemRed_body.tga"
    assert ap["head_tex"] == "Heads/HeadLiu/liu_head.tga"
