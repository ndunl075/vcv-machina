"""Word lists used to build meaningful pseudonyms (all invented combinations of common given names,
surnames and neutral nouns; none of them is taken from the corpus)."""

FIRST = """Adam Adela Adrian Agnes Aidan Alan Alba Alec Alice Alma Alvin Amber Amos Andre Angus Anita Anna Anton April Arlo Arman Arthur Asher Ada
Astrid Aubrey Ava Axel Barry Basil Beata Bella Ben Berta Beth Blair Bo Bram Brett Brian Bruno Caleb Cara Carl Carmen Cecil Celia Chad
Clara Clark Cleo Colin Cora Craig Cyrus Dale Dana Daniel Dara Dean Delia Denis Derek Diana Dino Dora Drew Duke Dylan Edgar Edith Edna
Eli Elena Elias Ella Elmer Elsa Emil Emma Enzo Eric Erik Erin Esme Ethan Eva Evan Ezra Faith Felix Fern Finn Flora Floyd Frank Freya
Gabe Gail Gary Gavin Gemma Gene Gil Gina Glen Gwen Hana Hank Hanna Harold Hazel Heidi Helen Henry Hugo Ian Ida Igor Iris Isaac Isla Ivan
Ivy Jack Jade Jake Jana Jane Jared Jason Jay Jean Jeff Jena Jill Joan Joel John Jon Jonas Jorge Josh Joy Juan Jude Julia Juno Kai Kara
Karl Kate Katia Keith Kent Kerri Kira Kyle Lara Larry Laura Lea Leo Leon Lena Lia Lily Lina Lisa Liv Lois Lola Lora Lucas Lucy Luis
Luke Lydia Lyle Mabel Mack Maia Mara Marco Maria Mark Marta Mary Matt Maya Mia Mike Mila Milo Mina Mona Muriel Myra Nadia Nate Neil
Nell Nico Nina Noah Nora Olga Olive Omar Oona Orla Oscar Otto Owen Pablo Paige Pam Paul Pearl Pedro Peggy Percy Perry Pete Petra Phil
Pia Quinn Rachel Rafa Ralph Raul Ray Rena Rhea Rhys Rita Rob Rosa Rose Ross Roy Ruby Rudi Ruth Ryan Sam Sara Saul Sean Selma Seth Shane
Sia Sid Silas Simon Sofia Sonia Stan Stella Sue Tara Ted Tess Thea Theo Tia Tim Tina Toby Tom Tony Tracy Troy Uma Una Val Vera Vic
Vida Vince Viola Walt Wanda Wes Will Wynn Xavi Yara Yuri Zach Zane Zara Zoe Zola""".split()

LAST = """Abbott Acker Adler Albrecht Alden Ambrose Anders Archer Ashby Atwood Avery Baines Baker Bannon Barlow Barton Bauer Beck Bell Bishop
Blake Boone Boyd Brandt Briggs Brock Brooks Burke Burns Byrne Cabot Cahill Cain Calder Carver Chase Clay Cobb Cole Conway Cook Cross
Crowe Dale Dalton Dawes Dean Delgado Dixon Doyle Drake Dunn Eaton Elder Ellis Emery Evans Faber Fagan Farrow Finch Fisher Flynn
Foley Ford Foster Fox Frost Fuller Gage Gale Garza Gentry Gibbs Gill Glass Gould Grady Greer Grove Hagen Hale Hall Hardy Hart Hayes
Heath Hess Hicks Hill Hoyt Hughes Hunt Hurst Irwin Jarvis Jensen Keane Keller Kemp Kerr Knox Lamb Lane Lang Lowe Lund Lyons Marsh
Mason Maxwell Mercer Miles Moody Moss Nash Nolan North Novak Oakes Olsen Orr Owens Pace Pardo Park Pearce Penn Pike Pratt Quill Rader
Ramos Reed Reyes Rhodes Rice Rowe Rush Sachs Sayer Shaw Sloan Snell Stark Stone Tate Thorn Todd Tran Trent Ulrich Vance Voss Wade
Wald Walsh Ward Webb Wells West Whit Wolfe Wyatt Yates York Young Zeller Zimmer Abel Barrett Bishop Calloway Dorsey Everett
Fairbanks Gallagher Hawthorne Ingram Jennings Kingsley Langford Montague Northcott Oakley Pemberton Quimby Ravenscroft Sinclair
Thornton Underhill Vandermeer Whitaker Yardley Ashworth Blackwell Carmichael Delacroix Eastwood Fitzgerald Grantham Hargrove""".split()

COMPANY_A = """Alder Apex Arbor Atlas Aurora Beacon Birch Bridge Cedar Cinder Cobalt Compass Copper Coral Crest Delta Ember Falcon Fjord Forge
Garnet Glacier Granite Harbor Helix Horizon Indigo Iron Juniper Keystone Lantern Lumen Maple Meridian Mesa Nimbus Northwind Oak Onyx
Orbit Pillar Pine Pioneer Prairie Quarry Raven Redwood Ridge River Sable Sierra Silver Slate Solstice Spruce Summit Tundra Vector
Vertex Willow Zenith Argon Axiom Boreal Cascade Dynamo Echo Fulcrum Gantry Hammer Ion Jasper Kinetic Lattice Magnet Nexus Optic
Pivot Quartz Rotor Sprocket Torque Vortex""".split()
COMPANY_B = """Dynamics Engineering Systems Technologies Robotics Mechanics Industries Works Labs Precision Instruments Machines Design
Fabrication Automation Controls Components Tooling Solutions Manufacturing Devices Motion Analytics Materials Aerospace Marine Energy
Optics Sensors Hydraulics Composites""".split()
COMPANY_SUFFIX = ["Inc", "Ltd", "GmbH", "LLC", "Corp", "AG", "BV", "SA", "Co", "Group"]

NOUN = """anchor arrow badger bandit basin beacon bison blade bolt bridge cable canyon carbon cargo castle cipher cobra comet condor coral
crane crown dagger delta dome drone eagle engine falcon ferry flint forge fox gadget gear glider hammer harbor hawk helix hinge
jackal kernel kite lancer lathe lever lynx magnet mantis marble mirror nomad otter owl panther piston plasma pulley quartz racer
radar rocket rotor sail scout shuttle sparrow spindle sprocket tiger torque tower turbine valve viper vortex wagon walrus widget wolf
yoke zephyr""".split()
ADJ = """agile amber ancient bold brisk bright calm clever cobalt cosmic crisp daring dusty eager fierce gentle golden hidden iron jolly keen
lively lunar mellow mighty noble olive polar quick quiet rapid rustic silent solar steady swift tidy urban vivid wild young zesty""".split()

TLDS = ["com", "net", "org", "io", "de", "co.uk", "fr", "nl", "se", "ch", "eu", "us", "ca", "info", "dev"]
