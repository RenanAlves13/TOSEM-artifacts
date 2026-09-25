[CmdletBinding()]
param(
    [string]$OutputPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $repoRoot 'docs\Static_Analysis_Methodology.docx'
}

$summaryPath = Join-Path $repoRoot 'analysis-results\static-analysis\project_summaries.csv'
$indexPath = Join-Path $repoRoot 'analysis-results\static-analysis\index.json'
if (-not (Test-Path -LiteralPath $summaryPath)) {
    throw "Static-analysis summary not found: $summaryPath"
}

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Escape-Xml {
    param([AllowNull()][object]$Text)
    if ($null -eq $Text) {
        return ''
    }
    return [System.Security.SecurityElement]::Escape([string]$Text)
}

function New-Run {
    param(
        [AllowEmptyString()][string]$Text,
        [switch]$Bold,
        [switch]$Italic,
        [int]$Size = 22,
        [string]$Color = ''
    )

    $properties = New-Object System.Collections.Generic.List[string]
    [void]$properties.Add('<w:rFonts w:ascii="Aptos" w:hAnsi="Aptos" w:cs="Aptos"/>')
    [void]$properties.Add("<w:sz w:val=`"$Size`"/>")
    [void]$properties.Add("<w:szCs w:val=`"$Size`"/>")
    if ($Bold) {
        [void]$properties.Add('<w:b/>')
    }
    if ($Italic) {
        [void]$properties.Add('<w:i/>')
    }
    if (-not [string]::IsNullOrWhiteSpace($Color)) {
        [void]$properties.Add("<w:color w:val=`"$Color`"/>")
    }

    return '<w:r><w:rPr>' + ($properties -join '') + '</w:rPr><w:t xml:space="preserve">' + (Escape-Xml $Text) + '</w:t></w:r>'
}

$script:Body = New-Object System.Text.StringBuilder

function Add-Xml {
    param([string]$Xml)
    [void]$script:Body.AppendLine($Xml)
}

function Add-Paragraph {
    param(
        [AllowEmptyString()][string]$Text,
        [string]$Style = 'Normal',
        [switch]$Bold,
        [switch]$Italic,
        [string]$Alignment = 'left',
        [int]$SpaceBefore = 0,
        [int]$SpaceAfter = 120,
        [int]$Size = 22,
        [string]$Color = ''
    )

    $paragraphProperties = New-Object System.Collections.Generic.List[string]
    if (-not [string]::IsNullOrWhiteSpace($Style)) {
        [void]$paragraphProperties.Add("<w:pStyle w:val=`"$Style`"/>")
    }
    [void]$paragraphProperties.Add("<w:spacing w:before=`"$SpaceBefore`" w:after=`"$SpaceAfter`" w:line=`"276`" w:lineRule=`"auto`"/>")
    if ($Alignment -ne 'left') {
        [void]$paragraphProperties.Add("<w:jc w:val=`"$Alignment`"/>")
    }
    Add-Xml ('<w:p><w:pPr>' + ($paragraphProperties -join '') + '</w:pPr>' + (New-Run -Text $Text -Bold:$Bold -Italic:$Italic -Size $Size -Color $Color) + '</w:p>')
}

function Add-Heading {
    param([string]$Text, [ValidateRange(1, 3)][int]$Level = 1)
    $headingSize = 23
    if ($Level -eq 1) {
        $headingSize = 30
    } elseif ($Level -eq 2) {
        $headingSize = 26
    }
    Add-Paragraph -Text $Text -Style ("Heading$Level") -Bold -SpaceBefore 240 -SpaceAfter 120 -Size $headingSize -Color '1F4E79'
}

function Add-Bullet {
    param([string]$Text, [ValidateRange(0, 4)][int]$Level = 0)
    $left = 360 + (360 * $Level)
    $paragraphProperties = '<w:pPr><w:spacing w:after="60"/><w:ind w:left="' + $left + '" w:hanging="180"/></w:pPr>'
    Add-Xml ('<w:p>' + $paragraphProperties + (New-Run -Text ('- ' + $Text) -Size 21) + '</w:p>')
}

function Add-PageBreak {
    Add-Xml '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'
}

function New-TableCell {
    param(
        [AllowNull()][object]$Text,
        [int]$Width,
        [bool]$Header = $false,
        [int]$FontSize = 18
    )
    $shading = if ($Header) { '<w:shd w:val="clear" w:fill="D9EAF7"/>' } else { '' }
    $run = if ($Header) {
        New-Run -Text ([string]$Text) -Bold -Size $FontSize
    } else {
        New-Run -Text ([string]$Text) -Size $FontSize
    }
    return '<w:tc><w:tcPr><w:tcW w:w="' + $Width + '" w:type="dxa"/>' + $shading + '<w:vAlign w:val="center"/></w:tcPr><w:p><w:pPr><w:spacing w:after="36"/><w:spacing w:before="36"/></w:pPr>' + $run + '</w:p></w:tc>'
}

function Add-Table {
    param(
        [string[]]$Headers,
        [object[]]$Rows,
        [int[]]$Widths,
        [int]$FontSize = 18
    )
    if ($Headers.Count -ne $Widths.Count) {
        throw 'Headers and widths must have the same number of columns.'
    }

    $table = New-Object System.Text.StringBuilder
    [void]$table.Append('<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/><w:tblLayout w:type="fixed"/><w:tblBorders><w:top w:val="single" w:sz="4" w:space="0" w:color="A6A6A6"/><w:left w:val="single" w:sz="4" w:space="0" w:color="A6A6A6"/><w:bottom w:val="single" w:sz="4" w:space="0" w:color="A6A6A6"/><w:right w:val="single" w:sz="4" w:space="0" w:color="A6A6A6"/><w:insideH w:val="single" w:sz="2" w:space="0" w:color="D9D9D9"/><w:insideV w:val="single" w:sz="2" w:space="0" w:color="D9D9D9"/></w:tblBorders><w:tblCellMar><w:top w:w="50" w:type="dxa"/><w:left w:w="70" w:type="dxa"/><w:bottom w:w="50" w:type="dxa"/><w:right w:w="70" w:type="dxa"/></w:tblCellMar></w:tblPr><w:tblGrid>')
    foreach ($width in $Widths) {
        [void]$table.Append('<w:gridCol w:w="' + $width + '"/>')
    }
    [void]$table.Append('</w:tblGrid><w:tr>')
    for ($index = 0; $index -lt $Headers.Count; $index += 1) {
        [void]$table.Append((New-TableCell -Text $Headers[$index] -Width $Widths[$index] -Header $true -FontSize $FontSize))
    }
    [void]$table.Append('</w:tr>')

    foreach ($row in $Rows) {
        [void]$table.Append('<w:tr>')
        for ($index = 0; $index -lt $Headers.Count; $index += 1) {
            $value = if ($index -lt $row.Count) { $row[$index] } else { '' }
            [void]$table.Append((New-TableCell -Text $value -Width $Widths[$index] -FontSize $FontSize))
        }
        [void]$table.Append('</w:tr>')
    }
    [void]$table.Append('</w:tbl>')
    Add-Xml $table.ToString()
    Add-Paragraph -Text '' -SpaceAfter 60 -Size 2
}

function Add-Callout {
    param([string]$Text)
    $cell = '<w:tc><w:tcPr><w:tcW w:w="9000" w:type="dxa"/><w:shd w:val="clear" w:fill="EAF2F8"/><w:tcMar><w:top w:w="120" w:type="dxa"/><w:left w:w="160" w:type="dxa"/><w:bottom w:w="120" w:type="dxa"/><w:right w:w="160" w:type="dxa"/></w:tcMar></w:tcPr><w:p><w:pPr><w:spacing w:after="0"/></w:pPr>' + (New-Run -Text $Text -Italic -Size 20 -Color '1F4E79') + '</w:p></w:tc>'
    Add-Xml ('<w:tbl><w:tblPr><w:tblW w:w="9000" w:type="dxa"/><w:tblBorders><w:top w:val="single" w:sz="4" w:space="0" w:color="9CC2E5"/><w:left w:val="single" w:sz="4" w:space="0" w:color="9CC2E5"/><w:bottom w:val="single" w:sz="4" w:space="0" w:color="9CC2E5"/><w:right w:val="single" w:sz="4" w:space="0" w:color="9CC2E5"/></w:tblBorders></w:tblPr><w:tr>' + $cell + '</w:tr></w:tbl>')
    Add-Paragraph -Text '' -SpaceAfter 60 -Size 2
}

function Format-Count {
    param([AllowNull()][object]$Value)
    $number = 0
    [void][int]::TryParse(([string]$Value), [ref]$number)
    return $number.ToString('N0', [System.Globalization.CultureInfo]::InvariantCulture)
}

function Sum-Column {
    param([object[]]$Rows, [string]$Column)
    $sum = 0L
    foreach ($row in $Rows) {
        $value = 0L
        [void][long]::TryParse(([string]$row.$Column), [ref]$value)
        $sum += $value
    }
    return $sum
}

$summaries = @(Import-Csv -LiteralPath $summaryPath)
$index = if (Test-Path -LiteralPath $indexPath) {
    Get-Content -LiteralPath $indexPath -Raw | ConvertFrom-Json
} else {
    $null
}
$snapshotTime = if ($null -ne $index -and $null -ne $index.generated_at_utc) { [string]$index.generated_at_utc } else { 'not recorded in index.json' }

$corpusRows = @()
foreach ($summary in $summaries) {
    $corpusRows += ,@(
        [string]$summary.project,
        (Format-Count $summary.build_files),
        (Format-Count $summary.java_files),
        (Format-Count $summary.analyzed_type_files),
        (Format-Count $summary.packages),
        (Format-Count $summary.methods),
        (Format-Count $summary.effective_source_lines),
        (Format-Count $summary.internal_imports),
        (Format-Count $summary.internal_package_dependencies),
        (Format-Count $summary.entrypoints)
    )
}

$totalBuildFiles = Sum-Column $summaries 'build_files'
$totalSubmodules = Sum-Column $summaries 'declared_submodules'
$totalRoots = Sum-Column $summaries 'source_roots'
$totalJavaFiles = Sum-Column $summaries 'java_files'
$totalDescriptors = Sum-Column $summaries 'java_descriptor_files'
$totalTypes = Sum-Column $summaries 'analyzed_type_files'
$totalPackages = Sum-Column $summaries 'packages'
$totalEntrypoints = Sum-Column $summaries 'entrypoints'
$totalMethods = Sum-Column $summaries 'methods'
$totalEffectiveLines = Sum-Column $summaries 'effective_source_lines'
$totalImports = Sum-Column $summaries 'imports'
$totalInternalImports = Sum-Column $summaries 'internal_imports'
$totalExternalImports = Sum-Column $summaries 'external_imports'
$totalEdges = Sum-Column $summaries 'package_dependency_edges'
$totalInternalEdges = Sum-Column $summaries 'internal_package_dependencies'
$totalExternalEdges = Sum-Column $summaries 'external_package_dependencies'
$totalInternalOccurrences = Sum-Column $summaries 'internal_package_dependency_occurrences'
$totalExternalOccurrences = Sum-Column $summaries 'external_package_dependency_occurrences'

# Title page
Add-Paragraph -Text 'Static Source-Code Analysis Procedure and Structural Evidence Construction' -Style 'Title' -Bold -Alignment 'center' -SpaceBefore 1320 -SpaceAfter 260 -Size 40 -Color '1F4E79'
Add-Paragraph -Text 'Methodological supplement for a software-architecture study' -Style 'Subtitle' -Alignment 'center' -SpaceAfter 520 -Size 26 -Color '5B6573'
Add-Paragraph -Text 'Repository-grounded description of the implemented source-based analysis' -Alignment 'center' -Italic -SpaceAfter 780 -Size 22 -Color '5B6573'
Add-Callout 'Scope note. This document describes the analysis actually implemented by static analysis/analyze_systems.py. It is a lightweight, offline, source-based procedure. It is not a compiler analysis, a bytecode analysis, a runtime trace, or a call-graph reconstruction.'
Add-Paragraph -Text ('Current artifact snapshot: ' + $snapshotTime + '. The generated corpus profile below contains ' + $summaries.Count + ' project(s).') -Alignment 'center' -SpaceAfter 0 -Size 19 -Color '5B6573'
Add-PageBreak

Add-Heading '1. Purpose and analytical scope' 1
Add-Paragraph 'The study uses static analysis to construct a reproducible layer of structural evidence for architectural reasoning. The procedure inspects Java source code, build descriptors, and explicit import declarations from the repository snapshot. Its purpose is to expose size, organization, and static coupling indicators that can contextualize a proposed service decomposition. It does not attempt to derive a uniquely correct microservice architecture.'
Add-Callout 'Recommended article wording: "The analysis produces structural evidence from source code, build descriptors, and explicit import declarations. It was not designed to reconstruct runtime behavior or to infer a uniquely correct microservice decomposition."'
Add-Paragraph 'The active analyzer is the Python standard-library runner located at static analysis/analyze_systems.py. Although the repository also contains a SootUp directory, the configured runner does not invoke SootUp. The implementation performs no Java compilation, Maven or Gradle execution, bytecode inspection, application execution, dynamic instrumentation, or dependency resolution against a build tool. This design was appropriate for an offline source-level inventory, including environments where Java and Maven are unavailable on PATH.'
Add-Paragraph 'For clarity in the article, the procedure should be described as source-based, regex-assisted static analysis. Terms such as call graph, runtime dependency, message flow, verified architectural layer, or ground-truth service boundary should not be used for these artifacts.'

Add-Heading '2. Inputs, corpus discovery, and execution' 1
Add-Paragraph 'The runner treats each immediate subdirectory of systems/ as a separate project. Project directories and discovered files are sorted, giving a stable traversal order for a fixed source snapshot. For every project, the analyzer recursively discovers Java files and build descriptors. It scans all remaining Java source categories, including main, test, UI-test, and other Java directories.'
Add-Table -Headers @('Element', 'Operational rule', 'Interpretation for the study') -Widths @(1800, 3500, 3700) -Rows @(
    @('Project unit', 'Each immediate child directory of systems/', 'One source-analysis unit; it is not necessarily one deployable application or one microservice.'),
    @('Java source', 'Recursive discovery of *.java outside ignored directories', 'All eligible Java source sets are included, including production and test-related code.'),
    @('Build descriptor', 'pom.xml, build.gradle, and build.gradle.kts', 'Evidence of build structure only; not a count of business modules or service candidates.'),
    @('Java descriptor', 'package-info.java and module-info.java', 'Counted as discovered Java descriptor files, but excluded from per-type records.'),
    @('Ignored directories', '.git, .github, .gradle, .idea, .vscode, build, dist, node_modules, out, target', 'Generated, IDE, dependency, and build-output directories are not scanned.')
) -FontSize 17
Add-Paragraph 'Source text is decoded by trying UTF-8, UTF-8 with BOM, and Latin-1, followed by UTF-8 with replacement if necessary. This permits analysis of heterogeneous legacy source trees without requiring a successful compilation environment.'
Add-Paragraph -Text 'Reproduction command' -Style 'Heading2' -Bold -SpaceBefore 160 -SpaceAfter 70 -Size 26 -Color '1F4E79'
Add-Callout 'python "static analysis\analyze_systems.py"'
Add-Paragraph 'The runner writes per-project results beneath analysis-results/static-analysis/ and writes an aggregate index at the same root. Fixed artifact names are overwritten for every project discovered in the current run. The implementation does not remove stale project directories that may remain from an earlier, broader corpus; a replication package should therefore archive or clean the output directory before a new corpus run and record the repository revision and analyzer version.'

Add-Heading '3. End-to-end analysis workflow' 1
Add-Paragraph 'The implemented workflow is summarized below. Every later aggregation is derived from per-file records created during the Java-source scan.'
Add-Table -Headers @('Step', 'Operation', 'Produced evidence') -Widths @(850, 4200, 3950) -Rows @(
    @('1', 'Discover project directories, build descriptors, and eligible Java files.', 'Sorted project and file inventories; ignored generated/build directories.'),
    @('2', 'Parse Maven or Gradle descriptors without executing a build.', 'Build tool, descriptor location, artifact identifier, packaging, Java-version cue, plugins, and declared submodules.'),
    @('3', 'Sanitize Java text for selected pattern matching and extract one record per non-descriptor file.', 'Package, imports, annotations, primary type, line counts, method counts, source-set label, role, and entrypoint cues.'),
    @('4', 'Construct project-wide known type and package sets, then classify imports.', 'Internal versus external import declarations and external dependency-root frequencies.'),
    @('5', 'Aggregate cross-package imports into weighted directed package relations.', 'Package dependencies and occurrence-weighted incoming/outgoing internal dependency measures.'),
    @('6', 'Write detailed per-project artifacts and consolidated corpus files.', 'CSV and JSON evidence for review, prompt construction, and reporting.')
) -FontSize 17
Add-Callout 'Pipeline lineage: systems/ -> project and build discovery -> Java-file scan -> per-file records -> package/import aggregation -> per-project artifacts -> consolidated index -> bounded prompt evidence.'

Add-Heading '4. Build-structure extraction and source-to-module mapping' 1
Add-Paragraph 'Every discovered pom.xml produces one Maven build-descriptor record. Maven extraction uses XML parsing to collect the root artifactId, direct packaging value (jar when omitted), selected Java-version properties (java.version, java.release, maven.compiler.release, maven.compiler.source, and maven.compiler.target), and direct modules/module declarations. If an XML parse error occurs, the runner retains a record containing parse_error and continues instead of aborting the project analysis.'
Add-Paragraph 'Each build.gradle or build.gradle.kts produces one Gradle build-descriptor record. The extractor uses regular expressions to identify plugin identifiers declared through the id syntax and selected Java-version patterns. Packaging is labeled war only when the detected plugin list contains war; otherwise it is labeled jar. This is intentionally a lightweight descriptor inspection: it does not execute Gradle, resolve dynamic scripts, or establish a complete dependency graph.'
Add-Paragraph 'A Java file is associated with the deepest enclosing directory that contains a discovered build descriptor. This source-to-module mapping is a path-based organizational association, not a semantic module model. Consequently, build_files and declared_submodules are reported as build-structure measures and must not be interpreted as business-module counts, microservice counts, or deployment-unit counts.'

Add-Heading '5. Java-source processing and file-level measures' 1
Add-Paragraph 'For each eligible Java file other than package-info.java and module-info.java, the procedure creates one source record. Comments and string or character literals are removed with regular expressions before primary type detection, method counting, and main-method matching. Package declarations, import declarations, and annotations are extracted from the original text. This distinction reduces obvious false matches in comments and literals while retaining syntactic declarations as written in the source.'
Add-Paragraph 'The primary type detector recognizes class, interface, enum, record, and annotation-type declarations. If several declarations occur in a file, it favors a declaration whose name matches the filename; otherwise it retains the first match. If no declaration is found, the file is retained with type kind unknown and the file stem as its type name. Thus, the legacy artifact name classes.csv should be read as analyzed Java type files: entries can denote classes, interfaces, enums, records, annotation types, or unknown declarations. Additional or nested types are not independently represented.'
Add-Table -Headers @('Measure', 'Construction rule', 'Interpretation and caveat') -Widths @(1850, 3650, 3500) -Rows @(
    @('source_lines', 'Physical number of lines in each analyzed type file.', 'A file-size measure; descriptors are excluded.'),
    @('effective_source_lines', 'Nonblank lines after regex-based comment removal.', 'A lightweight eLOC approximation, not a compiler or AST LOC metric.'),
    @('methods', 'Regex-detected method bodies plus constructors; an opening brace is required.', 'Approximate count; declaration-only, unusual, generated, or modern syntax can be missed.'),
    @('public_methods', 'Detected method/constructor signatures that contain public.', 'Uses the same signature heuristic and is not an API inventory.'),
    @('source_set', 'Path-derived label: main, test, ui-test, or other-java.', 'A diagnostic path label, not build-tool metadata; every label is included in the analysis.')
) -FontSize 17
Add-Paragraph 'The source-root heuristic searches for a src/.../java path. Exact trailing src/main/java and src/test/java paths become main and test, paths containing /ui_tests/ become ui-test, and all remaining files become other-java. Since this is a path heuristic rather than Maven or Gradle metadata, main_classes and test_classes should not be treated as authoritative production-versus-test totals. All source-set categories can contribute imports and package edges.'

Add-Heading '6. Heuristic roles and entrypoint candidates' 1
Add-Paragraph 'The analysis attaches one mutually exclusive role label to each analyzed type file. These labels are deterministic heuristic cues, not verified architectural classifications. The matching order matters: test and UI-test source-set labels take precedence, followed by recognized annotations, package-name tokens, a type-name suffix, and an other fallback. A type can therefore receive only one role even when its code exhibits several cross-cutting characteristics.'
Add-Table -Headers @('Priority', 'Evidence', 'Assigned role(s)') -Widths @(1050, 4950, 3000) -Rows @(
    @('1', 'source_set is test or ui-test', 'test'),
    @('2', 'Annotations: Controller, RestController, Path, WebServlet; Service; Repository; Configuration; Entity, Embeddable, MappedSuperclass, or Document', 'controller; service; repository; configuration; domain'),
    @('3', 'Package-name cues such as .controller, .web, .service, .dao, .domain, .event, .aspect, .exception, .persistence, .util, or .ui', 'controller, service, repository, domain, event, aspect, exception, persistence, utility, or ui'),
    @('4', 'Type name ends in Application', 'bootstrap'),
    @('5', 'No prior rule matches', 'other')
) -FontSize 16
Add-Paragraph 'Entrypoint candidates are stored when at least one cue is present: a public static void main method; SpringBootApplication or ApplicationPath; a controller-like annotation; or a type name ending in Application. The artifact preserves the reason or reasons. These candidates may include tests and do not establish routability, application startup success, endpoint completeness, or runtime reachability. They should be reported as heuristic entrypoint candidates.'
Add-Callout 'Recommended article wording: "Roles and entry points are heuristic labels derived from source paths, annotations, package names, and naming conventions; they are used as contextual evidence and not as ground-truth architectural classifications."'

Add-Heading '7. Import classification and package-dependency construction' 1
Add-Paragraph 'The dependency layer is constructed from syntactic Java import declarations, including wildcard and static imports. Before classifying them, the analyzer completes a first pass over the project to collect one fully qualified primary type and one package name from every analyzed type file. An explicit import is internal when it exactly matches a known fully qualified primary type or when its inferred target package exactly matches a known project package. A wildcard import is internal when its imported package is equal to, or an ancestor of, a known project package. All other imports are classified as external.'
Add-Paragraph 'For each import declaration, the target package is obtained by removing the final type/member segment, or by removing the wildcard suffix. A directed package relation is emitted only when source and target packages differ. Formally, each emitted relation is e = (p_s, p_t, c), where p_s is the importing package, p_t is the inferred imported package, and c is internal or external. Its weight w(e) is the number of import declarations aggregated into that same directed relation and category across all analyzed files.'
Add-Table -Headers @('Output measure', 'Definition', 'Do not interpret as') -Widths @(2400, 4000, 2600) -Rows @(
    @('internal_imports', 'All import declarations classified as internal, including same-package imports.', 'Runtime invocations or a call count.'),
    @('internal_package_dependencies', 'Number of distinct emitted internal source-package to target-package relations.', 'A global graph count across all projects, a message count, or a deployment dependency.'),
    @('internal_package_dependency_occurrences', 'Sum of the import-declaration weights over emitted internal package relations.', 'Distinct package-neighbor degree.'),
    @('incoming/outgoing_internal_dependencies', 'Occurrence-weighted sums for each package.', 'Unweighted in-degree or out-degree.'),
    @('external dependency root', 'First two segments for java, javax, and jakarta; first three segments otherwise.', 'Resolved library, artifact, or runtime dependency.')
) -FontSize 16
Add-Paragraph 'Same-package imports contribute to import totals but intentionally do not create package edges. Package relations may cross build-module boundaries because classification is based on the project-wide known type/package set. The classifier does not resolve fully qualified references without imports, inheritance, reflection, dependency injection, generated code, configuration-driven links, framework conventions, or runtime behavior. Static imports receive no special semantic resolution beyond the parsed target text.'
Add-Callout 'Recommended article wording: "Package relations represent aggregated static import declarations and are therefore interpreted as indicators of structural coupling, rather than as runtime calls, message exchanges, traffic volumes, or deployment dependencies."'

Add-Heading '8. Generated artifacts and aggregate outputs' 1
Add-Paragraph 'The runner writes six canonical artifacts for every discovered project. Lists are serialized as pipe-delimited text in CSV files. summary.json contains complete counts and selected highlights; the full CSV artifacts retain the detailed records needed for later inspection.'
Add-Table -Headers @('Artifact', 'Granularity', 'Main contents') -Widths @(2200, 1800, 5000) -Rows @(
    @('summary.json', 'Project', 'Project path and timestamp; build tools; complete counts; role and type-kind counts; source roots; top package roots; top internal dependencies; and frequent external roots.'),
    @('modules.csv', 'Build descriptor', 'Module path, tool, build file, artifact identifier, packaging, Java-version cue, plugins, declared submodules, and parse_error.'),
    @('classes.csv', 'Analyzed Java type file', 'Source set/root, file, package, type, role, LOC/eLOC, method counts, import counts, entrypoint flags/reasons, and annotations.'),
    @('package_dependencies.csv', 'Directed package relation', 'Source package, target package, internal/external category, and aggregated import-declaration weight.'),
    @('package_metrics.csv', 'Package', 'Type-file count, method counts, occurrence-weighted incoming/outgoing internal dependencies, and a role histogram.'),
    @('entrypoints.csv', 'Heuristic candidate', 'Module, package, type, source file, and entrypoint-detection reason(s).')
) -FontSize 16
Add-Paragraph 'At the analysis-results/static-analysis/ root, index.json records the projects analyzed and embeds their summaries; project_summaries.csv contains one aggregate-count row per project; and manifest.json declares the artifact layout. summary.json is concise but not exhaustive: its presentation highlights retain at most 10 package roots, 25 internal dependencies, and 20 external dependency roots. The detailed CSV files should be used whenever the full distribution is needed.'

Add-Heading '9. Use of static evidence in architecture-generation prompts' 1
Add-Paragraph 'The static-analysis loader reads the named per-project JSON and CSV artifacts into a structured data object. The prompt builder then produces a bounded textual summary instead of sending raw source code or an unbounded artifact dump. It includes summary counts, build tools, role counts, highlighted package roots, top internal dependencies, frequent external roots, detected modules, package metrics sorted by class count, internal dependency edges sorted by their weight, and heuristic entrypoints.'
Add-Paragraph 'The default prompt limits are 20 rows per displayed category and 18,000 characters for the static-evidence section. Standard classes.csv rows are retained in the loaded data for traceability but are not enumerated directly by the default static-evidence prompt builder. Other supplementary JSON, CSV, TXT, or Markdown artifacts can be previewed as extras, with additional limits. Therefore, architectural prompting consumes selected aggregate evidence while the static-analysis directory preserves the fuller source-derived record.'
Add-Callout 'Static evidence informs architectural reasoning; it does not prescribe service boundaries. Any generated decomposition must still be assessed against requirements and expert review criteria.'

Add-Heading '10. Current corpus profile' 1
Add-Paragraph ('The current project_summaries.csv snapshot, generated at ' + $snapshotTime + ', covers ' + $summaries.Count + ' projects, ' + (Format-Count $totalBuildFiles) + ' build descriptors, ' + (Format-Count $totalSubmodules) + ' declared submodules, ' + (Format-Count $totalRoots) + ' source roots, ' + (Format-Count $totalJavaFiles) + ' Java files, and ' + (Format-Count $totalDescriptors) + ' descriptor files excluded from per-type records. It contains ' + (Format-Count $totalTypes) + ' analyzed type files across ' + (Format-Count $totalPackages) + ' packages, ' + (Format-Count $totalMethods) + ' heuristic method/constructor matches, and ' + (Format-Count $totalEffectiveLines) + ' effective source lines.')
Add-Paragraph ('The aggregate of project-level counts contains ' + (Format-Count $totalImports) + ' import declarations (' + (Format-Count $totalInternalImports) + ' internal and ' + (Format-Count $totalExternalImports) + ' external), ' + (Format-Count $totalEdges) + ' distinct emitted package relations (' + (Format-Count $totalInternalEdges) + ' internal and ' + (Format-Count $totalExternalEdges) + ' external), and ' + (Format-Count $totalEntrypoints) + ' heuristic entrypoint candidates. The weighted occurrence totals are ' + (Format-Count $totalInternalOccurrences) + ' internal and ' + (Format-Count $totalExternalOccurrences) + ' external. These are sums of per-project measures, not counts on one globally deduplicated package graph.')
Add-Table -Headers @('Project', 'Build files', 'Java files', 'Type files', 'Packages', 'Methods', 'eLOC', 'Internal imports', 'Internal package edges', 'Entrypoint candidates') -Widths @(1050, 650, 700, 700, 620, 720, 800, 960, 1130, 880) -Rows $corpusRows -FontSize 14
Add-Paragraph 'Table interpretation: Type files denotes analyzed_type_files, which excludes Java descriptor files and is not restricted to class declarations. Internal package edges denotes the distinct internal source-package to target-package relations, not all package edges. For example, the current Cargo Tracker snapshot reports 110 internal package edges out of 313 total package edges, while TNTConcept reports 356 internal edges out of 931 total package edges.' -Style 'Caption' -Italic -SpaceAfter 120 -Size 18 -Color '5B6573'

Add-Heading '11. Reproducibility protocol for the article' 1
Add-Paragraph 'A replication package should preserve the source snapshot and record the exact conditions under which the analysis was generated. The runner itself records a generated_at_utc timestamp in each summary, but it does not capture all provenance needed for a standalone replication.'
Add-Bullet 'Record the repository revision or source archive checksum, the execution date, operating system, Python version, and the checksum or exact copy of static analysis/analyze_systems.py.'
Add-Bullet 'Archive the input systems/ snapshot and the resulting analysis-results/static-analysis/ directory together. Do not rely only on the current working tree.'
Add-Bullet 'Run the stated command from the repository root, then retain project_summaries.csv, index.json, manifest.json, and the six per-project artifacts.'
Add-Bullet 'Before regeneration, ensure that the output directory reflects the intended corpus. The runner overwrites current project artifacts but does not remove stale directories from a previous corpus.'
Add-Bullet 'Report whether test and UI-test sources remain included, as they do in the current implementation. If any later filtering is applied, report it as a separate post-processing step.'
Add-Bullet 'Use the terms source-based, import-derived, and heuristic consistently in the manuscript, tables, figure captions, and threats-to-validity discussion.'

Add-Heading '12. Limitations and interpretation boundaries' 1
Add-Paragraph 'The analysis is intentionally lightweight. Its validity is strongest as a consistent structural inventory and evidence source for the fixed repository snapshot, rather than as a full semantic program analysis. The following boundaries should be explicit in the article.'
Add-Bullet 'The Java extractor is regex-based, not AST- or compiler-based. Type, method, annotation, and entrypoint counts may have false positives or false negatives, especially with unusual syntax, nested types, multiline constructs, generated code, or declaration-only interface and abstract methods.'
Add-Bullet 'One primary type is recorded per Java file. Multiple top-level or nested declarations in the same file are not independently represented.'
Add-Bullet 'Role labels and entrypoint candidates are inferred from paths, annotations, package strings, and naming conventions. They are contextual indicators, not validated layer assignments or exhaustive interface inventories.'
Add-Bullet 'Import-derived relations omit fully qualified references without imports, reflection, dependency injection, configuration-driven links, generated code, framework-managed interactions, data stores, and runtime behavior.'
Add-Bullet 'An import edge is not evidence of a method invocation, HTTP request, asynchronous message, data-flow relation, traffic volume, deployment dependency, or temporal execution order.'
Add-Bullet 'Build descriptors are inspected without resolving parent POMs, dependencies, Gradle scripts, or build execution. Build-file counts must not be used as business-module or microservice counts.'
Add-Bullet 'Source-set labels are path-based and include tests in the evidence. They should not support strong production-code claims without independent validation.'
Add-Bullet 'No dedicated parser-accuracy test suite was identified for the runner; repository tests exercise surrounding UI/data integration rather than validating full Java-language coverage.'

Add-Heading 'Appendix A. Article-ready methodology text' 1
Add-Paragraph 'We implemented a lightweight, source-based static-analysis procedure to construct structural evidence for the architectural-decomposition task. The procedure processed each project directory under the study corpus and recursively inspected Java source files together with Maven and Gradle build descriptors. It was executed offline through a Python standard-library runner and did not compile or execute the systems, resolve dependencies through build tools, perform bytecode analysis, or collect runtime traces. Consequently, the resulting artifacts characterize source-level structure rather than dynamic behavior.'
Add-Paragraph 'For each eligible Java file, the analyzer extracted package declarations, import declarations, annotations, one primary type declaration, approximate method and public-method counts, physical and effective source-line counts, a path-derived source-set label, and heuristic role and entrypoint indicators. Comments and string literals were sanitized before selected pattern matches, while declarations were collected from the source text. Role labels were inferred from source-set, annotation, package-name, and naming cues, and entrypoint candidates were inferred from main-method, application, and controller-related cues. These labels were used as contextual evidence rather than as verified architectural facts.'
Add-Paragraph 'The dependency evidence was derived from explicit import declarations. After collecting the project-wide set of known source types and packages, imports were classified as internal or external and aggregated into directed source-package to target-package relations. The edge weight corresponds to the number of import declarations contributing to the relation. Accordingly, package relations were interpreted as indicators of static structural coupling, not as runtime calls, message exchanges, traffic volumes, deployment dependencies, or causal execution paths. The analysis produced project-level summaries, build-descriptor records, type-file records, package metrics, weighted package dependencies, and heuristic entrypoint records, along with a consolidated corpus summary.'
Add-Paragraph 'For architecture-generation prompts, the complete artifacts were retained for traceability, whereas a bounded summary of counts, build information, package metrics, prominent internal dependencies, external roots, and entrypoint candidates was provided as structural context. This separation ensured that static evidence informed architectural reasoning without being treated as a direct prescription of service boundaries. The study reports the procedure and its limitations explicitly because its regex-based extraction and import-derived relations are approximate by design.'

Add-Heading 'Appendix B. Suggested figure captions' 1
Add-Bullet 'Static-analysis pipeline: systems/ -> project and build discovery -> Java-file scan -> per-file records -> package/import aggregation -> per-project artifacts -> consolidated index -> bounded prompt evidence.'
Add-Bullet 'Import-to-package aggregation: several source files in one package may import types from another package; their declarations are aggregated into one weighted directed relation. The relation is not a runtime-call graph.'
Add-Bullet 'Artifact lineage: each project produces summary.json, modules.csv, classes.csv, package_dependencies.csv, package_metrics.csv, and entrypoints.csv; project_summaries.csv, index.json, and manifest.json consolidate the corpus.'

$documentXml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<w:document xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas" xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:wp14="http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" xmlns:w10="urn:schemas-microsoft-com:office:word" xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml" xmlns:w16cex="http://schemas.microsoft.com/office/word/2018/wordml/cex" xmlns:w16cid="http://schemas.microsoft.com/office/word/2016/wordml/cid" xmlns:w16="http://schemas.microsoft.com/office/word/2018/wordml" xmlns:w16du="http://schemas.microsoft.com/office/word/2023/wordml/word16du" xmlns:w16sdtdh="http://schemas.microsoft.com/office/word/2020/wordml/sdtdatahash" xmlns:w16sdtfl="http://schemas.microsoft.com/office/word/2024/wordml/sdtformatlock" xmlns:w16se="http://schemas.microsoft.com/office/word/2015/wordml/symex" xmlns:wpg="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup" xmlns:wpi="http://schemas.microsoft.com/office/word/2010/wordprocessingInk" xmlns:wne="http://schemas.microsoft.com/office/word/2006/wordml" xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" mc:Ignorable="w14 w15 w16se w16cid w16 w16cex w16sdtdh w16sdtfl w16du wp14"><w:body>' +
    $script:Body.ToString() +
    '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720" w:gutter="0"/><w:cols w:space="720"/><w:docGrid w:linePitch="360"/></w:sectPr></w:body></w:document>'

$stylesXml = @'
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:docDefaults>
    <w:rPrDefault><w:rPr><w:rFonts w:ascii="Aptos" w:hAnsi="Aptos" w:cs="Aptos"/><w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr></w:rPrDefault>
    <w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault>
  </w:docDefaults>
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
  <w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:qFormat/></w:style>
  <w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:basedOn w:val="Normal"/></w:style>
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/></w:pPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/></w:pPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/></w:pPr></w:style>
  <w:style w:type="paragraph" w:styleId="Caption"><w:name w:val="caption"/><w:basedOn w:val="Normal"/><w:pPr><w:jc w:val="left"/></w:pPr></w:style>
</w:styles>
'@

$contentTypesXml = @'
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>
'@

$rootRelationshipsXml = @'
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>
'@

$documentRelationshipsXml = @'
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>
'@

$generatedAt = [DateTime]::UtcNow.ToString('s') + 'Z'
$corePropertiesXml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>Static Source-Code Analysis Procedure and Structural Evidence Construction</dc:title><dc:creator>Research team</dc:creator><cp:lastModifiedBy>Research team</cp:lastModifiedBy><dcterms:created xsi:type="dcterms:W3CDTF">' + $generatedAt + '</dcterms:created><dcterms:modified xsi:type="dcterms:W3CDTF">' + $generatedAt + '</dcterms:modified></cp:coreProperties>'

$appPropertiesXml = @'
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Microsoft Office Word</Application>
  <DocSecurity>0</DocSecurity>
  <ScaleCrop>false</ScaleCrop>
  <Company></Company>
  <LinksUpToDate>false</LinksUpToDate>
  <SharedDoc>false</SharedDoc>
  <HyperlinksChanged>false</HyperlinksChanged>
  <AppVersion>16.0000</AppVersion>
</Properties>
'@

function Add-ZipText {
    param(
        [System.IO.Compression.ZipArchive]$Archive,
        [string]$Name,
        [string]$Content
    )
    $entry = $Archive.CreateEntry($Name, [System.IO.Compression.CompressionLevel]::Optimal)
    $stream = $entry.Open()
    $writer = New-Object System.IO.StreamWriter($stream, (New-Object System.Text.UTF8Encoding($false)))
    try {
        $writer.Write($Content)
    } finally {
        $writer.Dispose()
    }
}

$outputDirectory = [System.IO.Path]::GetDirectoryName([System.IO.Path]::GetFullPath($OutputPath))
[System.IO.Directory]::CreateDirectory($outputDirectory) | Out-Null
if (Test-Path -LiteralPath $OutputPath) {
    Remove-Item -LiteralPath $OutputPath -Force
}

$archive = [System.IO.Compression.ZipFile]::Open($OutputPath, [System.IO.Compression.ZipArchiveMode]::Create)
try {
    Add-ZipText -Archive $archive -Name '[Content_Types].xml' -Content $contentTypesXml
    Add-ZipText -Archive $archive -Name '_rels/.rels' -Content $rootRelationshipsXml
    Add-ZipText -Archive $archive -Name 'word/document.xml' -Content $documentXml
    Add-ZipText -Archive $archive -Name 'word/styles.xml' -Content $stylesXml
    Add-ZipText -Archive $archive -Name 'word/_rels/document.xml.rels' -Content $documentRelationshipsXml
    Add-ZipText -Archive $archive -Name 'docProps/core.xml' -Content $corePropertiesXml
    Add-ZipText -Archive $archive -Name 'docProps/app.xml' -Content $appPropertiesXml
} finally {
    $archive.Dispose()
}

[pscustomobject]@{
    OutputPath = [System.IO.Path]::GetFullPath($OutputPath)
    ProjectsDocumented = $summaries.Count
    GeneratedAtUtc = $generatedAt
}
