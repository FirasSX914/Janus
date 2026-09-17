"""Mapping des 145 classes WOS-46985 : id -> nom -> description.

Module commun, importe A L'IDENTIQUE par les deux runners, comme labels.py pour
Banking77. Tout changement ici deplace le prompt_hash des deux runs.

Le nom de classe est le COUPLE `Domain/area`. `Depression` et `Schizophrenia`
existent sous deux domaines differents, donc `area` seule n'identifie pas une
classe. Les couples viennent de `Meta-data/Data.xlsx` de l'archive Mendeley, la
seule source auto-coherente de l'archive -- voir data/README.md.

Les descriptions suivent un GABARIT UNIFORME : le domaine parent en toutes
lettres, puis l'aire. Contrairement a labels.py, ou les 77 descriptions ont ete
redigees une par une, aucune n'est ecrite a la main ici. C'est deliberé : a 145
classes, des descriptions redigees individuellement injecteraient une
connaissance inegale d'un domaine a l'autre, et le nom de l'aire est deja un
terme scientifique explicite. Le domaine parent est la seule information
supplementaire reellement utile, notamment pour les deux aires homonymes.

Les noms de domaine en toutes lettres sont ceux du ReadMe de l'archive.
"""

INSTRUCTIONS = "Which research area does this paper abstract belong to?"

# (id, nom, description). L'ordre, trie par (domaine, aire), fixe l'ordre des
# options envoyees et entre dans le prompt_hash.
LABELS: tuple[tuple[int, str, str], ...] = (
    (0, 'CS/Algorithm design', 'Computer science. Papers whose subject area is Algorithm design.'),
    (1, 'CS/Bioinformatics', 'Computer science. Papers whose subject area is Bioinformatics.'),
    (2, 'CS/Computer graphics', 'Computer science. Papers whose subject area is Computer graphics.'),
    (3, 'CS/Computer programming', 'Computer science. Papers whose subject area is Computer programming.'),
    (4, 'CS/Computer vision', 'Computer science. Papers whose subject area is Computer vision.'),
    (5, 'CS/Cryptography', 'Computer science. Papers whose subject area is Cryptography.'),
    (6, 'CS/Data structures', 'Computer science. Papers whose subject area is Data structures.'),
    (7, 'CS/Distributed computing', 'Computer science. Papers whose subject area is Distributed computing.'),
    (8, 'CS/Image processing', 'Computer science. Papers whose subject area is Image processing.'),
    (9, 'CS/Machine learning', 'Computer science. Papers whose subject area is Machine learning.'),
    (10, 'CS/Operating systems', 'Computer science. Papers whose subject area is Operating systems.'),
    (11, 'CS/Parallel computing', 'Computer science. Papers whose subject area is Parallel computing.'),
    (12, 'CS/Relational databases', 'Computer science. Papers whose subject area is Relational databases.'),
    (13, 'CS/Software engineering', 'Computer science. Papers whose subject area is Software engineering.'),
    (14, 'CS/Structured Storage', 'Computer science. Papers whose subject area is Structured Storage.'),
    (15, 'CS/Symbolic computation', 'Computer science. Papers whose subject area is Symbolic computation.'),
    (16, 'CS/network security', 'Computer science. Papers whose subject area is network security.'),
    (17, 'Civil/Ambient Intelligence', 'Civil engineering. Papers whose subject area is Ambient Intelligence.'),
    (18, 'Civil/Bamboo as a Building Material', 'Civil engineering. Papers whose subject area is Bamboo as a Building Material.'),
    (19, 'Civil/Construction Management', 'Civil engineering. Papers whose subject area is Construction Management.'),
    (20, 'Civil/Geotextile', 'Civil engineering. Papers whose subject area is Geotextile.'),
    (21, 'Civil/Green Building', 'Civil engineering. Papers whose subject area is Green Building.'),
    (22, 'Civil/Highway Network System', 'Civil engineering. Papers whose subject area is Highway Network System.'),
    (23, 'Civil/Nano Concrete', 'Civil engineering. Papers whose subject area is Nano Concrete.'),
    (24, 'Civil/Rainwater Harvesting', 'Civil engineering. Papers whose subject area is Rainwater Harvesting.'),
    (25, 'Civil/Remote Sensing', 'Civil engineering. Papers whose subject area is Remote Sensing.'),
    (26, 'Civil/Smart Material', 'Civil engineering. Papers whose subject area is Smart Material.'),
    (27, 'Civil/Solar Energy', 'Civil engineering. Papers whose subject area is Solar Energy.'),
    (28, 'Civil/Stealth Technology', 'Civil engineering. Papers whose subject area is Stealth Technology.'),
    (29, 'Civil/Suspension Bridge', 'Civil engineering. Papers whose subject area is Suspension Bridge.'),
    (30, 'Civil/Transparent Concrete', 'Civil engineering. Papers whose subject area is Transparent Concrete.'),
    (31, 'Civil/Underwater Windmill', 'Civil engineering. Papers whose subject area is Underwater Windmill.'),
    (32, 'Civil/Water Pollution', 'Civil engineering. Papers whose subject area is Water Pollution.'),
    (33, 'ECE/Analog signal processing', 'Electrical engineering. Papers whose subject area is Analog signal processing.'),
    (34, 'ECE/Control engineering', 'Electrical engineering. Papers whose subject area is Control engineering.'),
    (35, 'ECE/Digital control', 'Electrical engineering. Papers whose subject area is Digital control.'),
    (36, 'ECE/Electric motor', 'Electrical engineering. Papers whose subject area is Electric motor.'),
    (37, 'ECE/Electrical circuits', 'Electrical engineering. Papers whose subject area is Electrical circuits.'),
    (38, 'ECE/Electrical generator', 'Electrical engineering. Papers whose subject area is Electrical generator.'),
    (39, 'ECE/Electrical network', 'Electrical engineering. Papers whose subject area is Electrical network.'),
    (40, 'ECE/Electricity', 'Electrical engineering. Papers whose subject area is Electricity.'),
    (41, 'ECE/Lorentz force law', 'Electrical engineering. Papers whose subject area is Lorentz force law.'),
    (42, 'ECE/Microcontroller', 'Electrical engineering. Papers whose subject area is Microcontroller.'),
    (43, 'ECE/Operational amplifier', 'Electrical engineering. Papers whose subject area is Operational amplifier.'),
    (44, 'ECE/PID controller', 'Electrical engineering. Papers whose subject area is PID controller.'),
    (45, 'ECE/Satellite radio', 'Electrical engineering. Papers whose subject area is Satellite radio.'),
    (46, 'ECE/Signal-flow graph', 'Electrical engineering. Papers whose subject area is Signal-flow graph.'),
    (47, 'ECE/Single-phase electric power', 'Electrical engineering. Papers whose subject area is Single-phase electric power.'),
    (48, 'ECE/State space representation', 'Electrical engineering. Papers whose subject area is State space representation.'),
    (49, 'ECE/System identification', 'Electrical engineering. Papers whose subject area is System identification.'),
    (50, 'ECE/Voltage law', 'Electrical engineering. Papers whose subject area is Voltage law.'),
    (51, 'MAE/Fluid mechanics', 'Mechanical engineering. Papers whose subject area is Fluid mechanics.'),
    (52, 'MAE/Hydraulics', 'Mechanical engineering. Papers whose subject area is Hydraulics.'),
    (53, 'MAE/Internal combustion engine', 'Mechanical engineering. Papers whose subject area is Internal combustion engine.'),
    (54, 'MAE/Machine design', 'Mechanical engineering. Papers whose subject area is Machine design.'),
    (55, 'MAE/Manufacturing engineering', 'Mechanical engineering. Papers whose subject area is Manufacturing engineering.'),
    (56, 'MAE/Materials Engineering', 'Mechanical engineering. Papers whose subject area is Materials Engineering.'),
    (57, 'MAE/Strength of materials', 'Mechanical engineering. Papers whose subject area is Strength of materials.'),
    (58, 'MAE/Thermodynamics', 'Mechanical engineering. Papers whose subject area is Thermodynamics.'),
    (59, 'MAE/computer-aided design', 'Mechanical engineering. Papers whose subject area is computer-aided design.'),
    (60, 'Medical/Addiction', 'Medical science. Papers whose subject area is Addiction.'),
    (61, 'Medical/Allergies', 'Medical science. Papers whose subject area is Allergies.'),
    (62, "Medical/Alzheimer's Disease", "Medical science. Papers whose subject area is Alzheimer's Disease."),
    (63, 'Medical/Ankylosing Spondylitis', 'Medical science. Papers whose subject area is Ankylosing Spondylitis.'),
    (64, 'Medical/Anxiety', 'Medical science. Papers whose subject area is Anxiety.'),
    (65, 'Medical/Asthma', 'Medical science. Papers whose subject area is Asthma.'),
    (66, 'Medical/Atopic Dermatitis', 'Medical science. Papers whose subject area is Atopic Dermatitis.'),
    (67, 'Medical/Atrial Fibrillation', 'Medical science. Papers whose subject area is Atrial Fibrillation.'),
    (68, 'Medical/Autism', 'Medical science. Papers whose subject area is Autism.'),
    (69, 'Medical/Bipolar Disorder', 'Medical science. Papers whose subject area is Bipolar Disorder.'),
    (70, 'Medical/Birth Control', 'Medical science. Papers whose subject area is Birth Control.'),
    (71, 'Medical/Cancer', 'Medical science. Papers whose subject area is Cancer.'),
    (72, "Medical/Children's Health", "Medical science. Papers whose subject area is Children's Health."),
    (73, "Medical/Crohn's Disease", "Medical science. Papers whose subject area is Crohn's Disease."),
    (74, 'Medical/Dementia', 'Medical science. Papers whose subject area is Dementia.'),
    (75, 'Medical/Depression', 'Medical science. Papers whose subject area is Depression.'),
    (76, 'Medical/Diabetes', 'Medical science. Papers whose subject area is Diabetes.'),
    (77, 'Medical/Digestive Health', 'Medical science. Papers whose subject area is Digestive Health.'),
    (78, 'Medical/Emergency Contraception', 'Medical science. Papers whose subject area is Emergency Contraception.'),
    (79, 'Medical/Fungal Infection', 'Medical science. Papers whose subject area is Fungal Infection.'),
    (80, 'Medical/HIV/AIDS', 'Medical science. Papers whose subject area is HIV/AIDS.'),
    (81, 'Medical/Headache', 'Medical science. Papers whose subject area is Headache.'),
    (82, 'Medical/Healthy Sleep', 'Medical science. Papers whose subject area is Healthy Sleep.'),
    (83, 'Medical/Heart Disease', 'Medical science. Papers whose subject area is Heart Disease.'),
    (84, 'Medical/Hepatitis C', 'Medical science. Papers whose subject area is Hepatitis C.'),
    (85, 'Medical/Hereditary Angioedema', 'Medical science. Papers whose subject area is Hereditary Angioedema.'),
    (86, 'Medical/Hypothyroidism', 'Medical science. Papers whose subject area is Hypothyroidism.'),
    (87, 'Medical/Idiopathic Pulmonary Fibrosis', 'Medical science. Papers whose subject area is Idiopathic Pulmonary Fibrosis.'),
    (88, 'Medical/Irritable Bowel Syndrome', 'Medical science. Papers whose subject area is Irritable Bowel Syndrome.'),
    (89, 'Medical/Kidney Health', 'Medical science. Papers whose subject area is Kidney Health.'),
    (90, 'Medical/Low Testosterone', 'Medical science. Papers whose subject area is Low Testosterone.'),
    (91, 'Medical/Lymphoma', 'Medical science. Papers whose subject area is Lymphoma.'),
    (92, 'Medical/Medicare', 'Medical science. Papers whose subject area is Medicare.'),
    (93, 'Medical/Menopause', 'Medical science. Papers whose subject area is Menopause.'),
    (94, 'Medical/Mental Health', 'Medical science. Papers whose subject area is Mental Health.'),
    (95, 'Medical/Migraine', 'Medical science. Papers whose subject area is Migraine.'),
    (96, 'Medical/Multiple Sclerosis', 'Medical science. Papers whose subject area is Multiple Sclerosis.'),
    (97, 'Medical/Myelofibrosis', 'Medical science. Papers whose subject area is Myelofibrosis.'),
    (98, 'Medical/Osteoarthritis', 'Medical science. Papers whose subject area is Osteoarthritis.'),
    (99, 'Medical/Osteoporosis', 'Medical science. Papers whose subject area is Osteoporosis.'),
    (100, 'Medical/Outdoor Health', 'Medical science. Papers whose subject area is Outdoor Health.'),
    (101, 'Medical/Overactive Bladder', 'Medical science. Papers whose subject area is Overactive Bladder.'),
    (102, 'Medical/Parenting', 'Medical science. Papers whose subject area is Parenting.'),
    (103, "Medical/Parkinson's Disease", "Medical science. Papers whose subject area is Parkinson's Disease."),
    (104, 'Medical/Polycythemia Vera', 'Medical science. Papers whose subject area is Polycythemia Vera.'),
    (105, 'Medical/Psoriasis', 'Medical science. Papers whose subject area is Psoriasis.'),
    (106, 'Medical/Psoriatic Arthritis', 'Medical science. Papers whose subject area is Psoriatic Arthritis.'),
    (107, 'Medical/Rheumatoid Arthritis', 'Medical science. Papers whose subject area is Rheumatoid Arthritis.'),
    (108, 'Medical/Schizophrenia', 'Medical science. Papers whose subject area is Schizophrenia.'),
    (109, 'Medical/Senior Health', 'Medical science. Papers whose subject area is Senior Health.'),
    (110, 'Medical/Skin Care', 'Medical science. Papers whose subject area is Skin Care.'),
    (111, 'Medical/Smoking Cessation', 'Medical science. Papers whose subject area is Smoking Cessation.'),
    (112, 'Medical/Sports Injuries', 'Medical science. Papers whose subject area is Sports Injuries.'),
    (113, 'Medical/Sprains and Strains', 'Medical science. Papers whose subject area is Sprains and Strains.'),
    (114, 'Medical/Stress Management', 'Medical science. Papers whose subject area is Stress Management.'),
    (115, 'Medical/Weight Loss', 'Medical science. Papers whose subject area is Weight Loss.'),
    (116, 'Psychology/Antisocial personality disorder', 'Psychology. Papers whose subject area is Antisocial personality disorder.'),
    (117, 'Psychology/Attention', 'Psychology. Papers whose subject area is Attention.'),
    (118, 'Psychology/Borderline personality disorder', 'Psychology. Papers whose subject area is Borderline personality disorder.'),
    (119, 'Psychology/Child abuse', 'Psychology. Papers whose subject area is Child abuse.'),
    (120, 'Psychology/Depression', 'Psychology. Papers whose subject area is Depression.'),
    (121, 'Psychology/Eating disorders', 'Psychology. Papers whose subject area is Eating disorders.'),
    (122, 'Psychology/False memories', 'Psychology. Papers whose subject area is False memories.'),
    (123, 'Psychology/Gender roles', 'Psychology. Papers whose subject area is Gender roles.'),
    (124, 'Psychology/Leadership', 'Psychology. Papers whose subject area is Leadership.'),
    (125, 'Psychology/Media violence', 'Psychology. Papers whose subject area is Media violence.'),
    (126, 'Psychology/Nonverbal communication', 'Psychology. Papers whose subject area is Nonverbal communication.'),
    (127, 'Psychology/Person perception', 'Psychology. Papers whose subject area is Person perception.'),
    (128, 'Psychology/Prejudice', 'Psychology. Papers whose subject area is Prejudice.'),
    (129, 'Psychology/Prenatal development', 'Psychology. Papers whose subject area is Prenatal development.'),
    (130, 'Psychology/Problem-solving', 'Psychology. Papers whose subject area is Problem-solving.'),
    (131, 'Psychology/Prosocial behavior', 'Psychology. Papers whose subject area is Prosocial behavior.'),
    (132, 'Psychology/Schizophrenia', 'Psychology. Papers whose subject area is Schizophrenia.'),
    (133, 'Psychology/Seasonal affective disorder', 'Psychology. Papers whose subject area is Seasonal affective disorder.'),
    (134, 'Psychology/Social cognition', 'Psychology. Papers whose subject area is Social cognition.'),
    (135, 'biochemistry/Cell biology', 'Biochemistry. Papers whose subject area is Cell biology.'),
    (136, 'biochemistry/DNA/RNA sequencing', 'Biochemistry. Papers whose subject area is DNA/RNA sequencing.'),
    (137, 'biochemistry/Enzymology', 'Biochemistry. Papers whose subject area is Enzymology.'),
    (138, 'biochemistry/Genetics', 'Biochemistry. Papers whose subject area is Genetics.'),
    (139, 'biochemistry/Human Metabolism', 'Biochemistry. Papers whose subject area is Human Metabolism.'),
    (140, 'biochemistry/Immunology', 'Biochemistry. Papers whose subject area is Immunology.'),
    (141, 'biochemistry/Molecular biology', 'Biochemistry. Papers whose subject area is Molecular biology.'),
    (142, 'biochemistry/Northern blotting', 'Biochemistry. Papers whose subject area is Northern blotting.'),
    (143, 'biochemistry/Polymerase chain reaction', 'Biochemistry. Papers whose subject area is Polymerase chain reaction.'),
    (144, 'biochemistry/Southern blotting', 'Biochemistry. Papers whose subject area is Southern blotting.'),)

LABEL_NAMES: tuple[str, ...] = tuple(name for _, name, _ in LABELS)

CRITERIA: dict[str, str] = {name: description for _, name, description in LABELS}

# Domaine parent de chaque classe. Sert UNIQUEMENT a ventiler les erreurs entre
# celles qui restent dans le meme parent et celles qui le traversent ; n'entre
# ni dans le prompt, ni dans le prompt_hash, ni dans la mesure du seuil.
PARENTS: dict[str, str] = {name: name.split("/", 1)[0] for _, name, _ in LABELS}

assert len(LABELS) == 145, len(LABELS)
assert len(CRITERIA) == 145, "noms de classes dupliques"
assert [i for i, _, _ in LABELS] == list(range(145)), "ids non contigus"
assert len(set(PARENTS.values())) == 7, sorted(set(PARENTS.values()))
