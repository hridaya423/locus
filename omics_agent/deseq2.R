#!/usr/bin/env Rscript
# Gene counts and differential expression for one two-condition contrast, from salmon quantifications.
#
#   Rscript deseq2.R samples.tsv tx2gene.tsv outdir reference target
#
# samples.tsv has the columns sample, condition and quant (the salmon output directory). Writes counts.tsv (integer
# gene counts, genes x samples), deseq2_results.tsv, normalized_counts.tsv, pca/volcano/ma as JSON and PNG, and
# deseq2_summary.json with the numbers the CLI prints.

suppressPackageStartupMessages({
  library(tximport)
  library(DESeq2)
  library(apeglm)
  library(ggplot2)
  library(jsonlite)
})

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 5) stop("usage: deseq2.R samples.tsv tx2gene.tsv outdir reference target")
samples <- read.delim(args[1], stringsAsFactors = FALSE, check.names = FALSE)
tx2gene <- read.delim(args[2], stringsAsFactors = FALSE)
out <- args[3]
reference <- args[4]
target <- args[5]
dir.create(out, showWarnings = FALSE, recursive = TRUE)
path <- function(name) file.path(out, name)
tsv <- function(frame, name) write.table(frame, path(name), sep = "\t", quote = FALSE, row.names = FALSE)

# Gene-level counts: tximport sums transcript counts per gene and carries the average transcript length as an offset.
files <- setNames(file.path(samples$quant, "quant.sf"), samples$sample)
txi <- tximport(files, type = "salmon", tx2gene = tx2gene[, c("transcript_id", "gene_id")], countsFromAbundance = "no")
counts <- round(txi$counts)
storage.mode(counts) <- "integer"
tsv(data.frame(gene_id = rownames(counts), counts, check.names = FALSE), "counts.tsv")

# The reference level comes first, so coefficient 2 is target vs reference.
samples$condition <- factor(samples$condition, levels = c(reference, target))
dds <- DESeqDataSetFromTximport(txi, samples, ~condition)
dds <- dds[rowSums(counts(dds)) >= 10, ]
dds <- DESeq(dds, quiet = TRUE)
unshrunk <- results(dds, alpha = 0.05)
res <- lfcShrink(dds, coef = 2, res = unshrunk, type = "apeglm", quiet = TRUE)

names <- unique(tx2gene[, c("gene_id", "gene_name")])
gene_name <- setNames(names$gene_name, names$gene_id)
table <- data.frame(
  gene_id = rownames(res), gene_name = unname(gene_name[rownames(res)]),
  baseMean = res$baseMean, log2FoldChange = res$log2FoldChange, lfcSE = res$lfcSE, pvalue = res$pvalue, padj = res$padj,
  stringsAsFactors = FALSE
)
table <- table[order(table$padj, table$pvalue), ]
tsv(table, "deseq2_results.tsv")
normalized <- counts(dds, normalized = TRUE)
tsv(data.frame(gene_id = rownames(normalized), round(normalized, 2), check.names = FALSE), "normalized_counts.tsv")

# PCA on variance-stabilised counts; vst needs 1000 genes for its fit, so small inputs use the slower exact transform.
vsd <- tryCatch(vst(dds, blind = TRUE), error = function(e) varianceStabilizingTransformation(dds, blind = TRUE))
pca <- plotPCA(vsd, intgroup = "condition", returnData = TRUE)
variance <- round(100 * attr(pca, "percentVar"), 1)
means <- lapply(split(pca[, c("PC1", "PC2")], pca$condition), function(p) list(PC1 = round(mean(p$PC1), 2), PC2 = round(mean(p$PC2), 2)))
pca_points <- data.frame(sample = pca$name, condition = as.character(pca$condition), PC1 = round(pca$PC1, 3), PC2 = round(pca$PC2, 3))
write_json(list(points = pca_points, variance = variance, means = means), path("pca.json"), auto_unbox = TRUE, digits = NA)

# The web plots get every significant gene plus a fixed random sample of the rest, so the browser draws thousands of
# points, not tens of thousands. The PNGs and the results table keep every gene.
tested <- table[!is.na(table$padj), ]
tested$significant <- tested$padj < 0.05
set.seed(1)
rest <- which(!tested$significant)
shown <- tested[sort(c(which(tested$significant), rest[sample.int(length(rest), min(4000, length(rest)))])), ]
write_json(
  data.frame(gene = ifelse(is.na(shown$gene_name) | shown$gene_name == "", shown$gene_id, shown$gene_name), log2fc = round(shown$log2FoldChange, 3),
             neglog10p = round(-log10(pmax(shown$pvalue, 1e-300)), 3), padj = signif(shown$padj, 3), significant = shown$significant),
  path("volcano.json"), digits = NA
)
write_json(
  data.frame(gene = ifelse(is.na(shown$gene_name) | shown$gene_name == "", shown$gene_id, shown$gene_name), log10_mean = round(log10(shown$baseMean), 3),
             log2fc = round(shown$log2FoldChange, 3), padj = signif(shown$padj, 3), significant = shown$significant),
  path("ma.json"), digits = NA
)

theme_set(theme_minimal(base_size = 13) + theme(panel.grid.minor = element_blank(), legend.position = "top"))
palette <- c("#5B6B7A", "#C8553D")
names(palette) <- c(reference, target)
label <- function(gene) ifelse(is.na(gene$gene_name) | gene$gene_name == "", gene$gene_id, gene$gene_name)
ggsave(path("pca.png"), width = 7, height = 5.5, dpi = 200,
  ggplot(pca_points, aes(PC1, PC2, colour = condition)) + geom_point(size = 3.5) + scale_colour_manual(values = palette) +
    labs(x = sprintf("PC1 (%s%%)", variance[1]), y = sprintf("PC2 (%s%%)", variance[2]), colour = NULL, title = "PCA of variance-stabilised counts"))
top <- head(tested[tested$significant, ], 12)
ggsave(path("volcano.png"), width = 7, height = 5.5, dpi = 200,
  ggplot(tested, aes(log2FoldChange, -log10(pmax(pvalue, 1e-300)))) +
    geom_point(aes(colour = significant), size = 1, alpha = 0.6) + scale_colour_manual(values = c(`FALSE` = "#B8BEC4", `TRUE` = "#C8553D"), guide = "none") +
    geom_text(data = top, aes(label = label(top)), size = 3, vjust = -0.6, check_overlap = TRUE) +
    labs(x = sprintf("log2 fold change (%s vs %s, apeglm)", target, reference), y = "-log10 p-value", title = sprintf("%d genes with padj < 0.05", sum(tested$significant))))
ggsave(path("ma.png"), width = 7, height = 5.5, dpi = 200,
  ggplot(tested, aes(baseMean, log2FoldChange)) + geom_point(aes(colour = significant), size = 1, alpha = 0.6) + scale_x_log10() +
    scale_colour_manual(values = c(`FALSE` = "#B8BEC4", `TRUE` = "#C8553D"), guide = "none") + geom_hline(yintercept = 0, linetype = 2) +
    labs(x = "mean of normalised counts", y = sprintf("log2 fold change (%s vs %s, apeglm)", target, reference), title = "MA plot"))

write_json(list(
  genes = nrow(counts), genes_tested = nrow(dds), genes_with_padj = nrow(tested),
  significant = sum(tested$significant), up = sum(tested$significant & tested$log2FoldChange > 0), down = sum(tested$significant & tested$log2FoldChange < 0),
  pca = list(variance = variance, means = means),
  versions = list(R = as.character(getRversion()), DESeq2 = as.character(packageVersion("DESeq2")), tximport = as.character(packageVersion("tximport")),
                  apeglm = as.character(packageVersion("apeglm")), ggplot2 = as.character(packageVersion("ggplot2")))
), path("deseq2_summary.json"), auto_unbox = TRUE, digits = NA, pretty = TRUE)
