# product.md

## Who
Generates proteomics datasets in Parkinson's and Alzheimer's models (primary neurons and astrocytes, iPSC-derived and induced neurons, mouse models), using mitochondria and lysosome organelle IPs measured by proteomics, phosphoproteomics and ubiquitylomics. Own words: "generation of proteomic datasets in models for neurodegeneration".

## Pain, in their words
1. **Public data comes from papers' supplementary Excel files, not databases.** "i did not do that- maybe i shoudl improve this part of my work"; when comparing with others: "read paper on supplementary data", then "excel file, manually analysis". Time lost: not given.
2. **Filtering, then copying and pasting between Excel files.** "filtering and copy and paste to another file", filtering on "p-value fold change cutoffs". Time lost: "about days". "teh overlap require to download the excel files from th epaper and reprocees that data agian as for my analysis".
3. **Published data is already processed differently, so a fair comparison needs raw files.** "publica data from paper are often filtered or processed by the authors- so th ecomaprison with your own data requires th eacquisiion of the raw data from open repository and reprocessing the data as for your analysis and ultimately comapring them". Time lost: led them to abandon the analysis (see next section).

Interviewer note: searching public repositories (e.g. PRIDE) is not part of their current workflow at all, so the tool may need to create this habit, not just speed it up.

## The question they gave up on
Comparing the mitochondrial enrichment of proteins in their own mito-IP with published datasets: "Hansen et al. 2023, Morais et al. 2014, Science —Stauch et al. 2014 JPR / 2015 Proteomics". What stopped them: "they use different ways to analyse and normalize samples for enrichment. I stopped the analysi because you need to reproccess raw files in order to compare your datasets with the others already published".

Interviewer note: references are recorded exactly as given and were not checked.

## The Monday-morning ask
"collect all the datasets available for organelle proteins, generate a list of protein signatures for the all organelles, eg lysosome, mitochondria, er, synapsis etc... generate a organelle compandium with the most up to date datasets and also validate for each organelle profiling. that would be the starting point. then make a profile of these organelles for each tissues, such as if there is a singature of proteins that is most representative or unique in the brain or heart, etc."

What "validate" means: "if we identify a protein X as lysosome protein if there is any reported data that corroborate that finding either computational or by orthogonal assays like imaging, western blot and so on".

## Trust
What the tool must show:
- Evidence sources: "MitoCarta, agreement across several independent datasets, imaging or localisation evidence like the Human Protein Atlas, yes and also if any papers reported with any type of assay". Interviewer note: the first three were examples I offered and they confirmed; the papers-with-any-assay point is their own addition.
- A positive control that the method works: "we need to have a list of proteins that profile with what is conventional recognised as belonging to that organelle. So if in my experiment i do an IP of mitochondrial and I find 400 proeins comming down with my IP, first check how many proteins are actually mitochondrai comapring them with mitocarta. so measure the mitochondrial recovery., if the recovery is low i woudl reconsidering experimental design or analysis".

Where AI has failed them: "tha ai something reported wrong references".

Interviewer note: since their idea of validation depends on citing papers, every reference the tool gives must be real and checkable.

## Reaction to the direction
Most valuable: "delivery data ready for analysis abd find studies that measured several data".

Missing: "i would add the skill once you got your datasets, the possibility to analysed m and comparing them", i.e. analysis and comparison after delivery, not just data retrieval.

Interviewer note: based on their earlier answers, "ready for analysis" probably means reprocessed from raw files the same way as their own data, not the authors' processed tables. They did not confirm this directly.

## Demo candidate
Research question: "compare my mito-ip with mitocarta, and also with a database generated collecting all the published databases published for mitochondrial enrichment".

Data: "my data can be used for the demo" (their own mito-IP). Published comparison datasets they named: Hansen et al. 2023; Morais et al. 2014 (Science); Stauch et al. 2014 (JPR) / 2015 (Proteomics).

Known result to check against: "use a list of proteins that come out enriched", i.e. known mitochondrial proteins should come out enriched, and mitochondrial recovery against MitoCarta should be high.

## Their ideal product
A tool that collects published organelle proteomics datasets (starting with mitochondria, then lysosome, ER, synapse and others) and turns them into a validated organelle compendium, where every protein assigned to an organelle is backed by MitoCarta, the Human Protein Atlas, agreement across independent datasets, or papers that report it with any assay, with real, checkable references. It would then let them drop in their own organelle IP results, report organelle recovery as a quality check, and compare their enrichment with published studies on equal terms, without days of filtering and copy-pasting Excel supplementary tables or reprocessing raw files by hand. Later, it would profile each organelle by tissue to find brain- or heart-specific signatures.
