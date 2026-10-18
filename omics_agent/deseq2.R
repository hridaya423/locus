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
out_path <- function(name) file.path(out, name)
tsv <- function(frame, name) write.table(frame, out_path(name), sep = "\t", quote = FALSE, row.names = FALSE)

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
write_json(list(points = pca_points, variance = variance, means = means), out_path("pca.json"), auto_unbox = TRUE, digits = NA)

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
  out_path("volcano.json"), digits = NA
)
write_json(
  data.frame(gene = ifelse(is.na(shown$gene_name) | shown$gene_name == "", shown$gene_id, shown$gene_name), log10_mean = round(log10(shown$baseMean), 3),
             log2fc = round(shown$log2FoldChange, 3), padj = signif(shown$padj, 3), significant = shown$significant),
  out_path("ma.json"), digits = NA
)

# ---------------------------------------------------------------- figures
# One style for every panel (see the dataviz skill): white panel, thin axis lines, no gridlines, 9 pt sans, legend
# inside the panel. Conditions use the validated categorical pair blue/orange; the same hex values colour the web panel.
suppressPackageStartupMessages({
  library(ggrepel)
  library(pheatmap)
})
theme_locus <- function(base_size = 9) {
  theme_classic(base_size = base_size) +
    theme(
      axis.line = element_line(linewidth = 0.3, colour = "#52514e"), axis.ticks = element_line(linewidth = 0.3, colour = "#52514e"),
      axis.text = element_text(colour = "#52514e"), axis.title = element_text(colour = "#0b0b0b"),
      plot.title = element_text(size = base_size + 1, hjust = 0, colour = "#0b0b0b"), plot.title.position = "plot",
      plot.subtitle = element_text(size = base_size - 1, colour = "#52514e"),
      legend.title = element_blank(), legend.text = element_text(size = base_size - 1), legend.key.size = unit(8, "pt"),
      legend.background = element_blank(), legend.position = "inside",
      strip.background = element_blank(), strip.text = element_text(size = base_size, face = "italic", hjust = 0),
      plot.margin = margin(6, 8, 4, 4), plot.background = element_rect(fill = "white", colour = NA)
    )
}
COND <- setNames(c("#2a78d6", "#eb6834"), c(reference, target))
STATE <- c(`not significant` = "#c2c6ca", `padj < 0.05` = "#2a78d6", `padj < 0.05, |log2FC| ≥ 1` = "#eb6834")
BLUES <- c("#0d366b", "#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4", "#cde2fb")
plots <- file.path(out, "plots")
dir.create(plots, showWarnings = FALSE)
# Every figure goes out as a 300 dpi PNG for slides and a PDF for a manuscript, at a stated physical size (inches).
save_figure <- function(name, plot, width, height) {
  ggsave(file.path(plots, paste0(name, ".png")), plot, width = width, height = height, dpi = 300, bg = "white")
  ggsave(file.path(plots, paste0(name, ".pdf")), plot, width = width, height = height, device = cairo_pdf, bg = "white")
}
symbol <- function(frame) ifelse(is.na(frame$gene_name) | frame$gene_name == "", frame$gene_id, frame$gene_name)
contrast_label <- sprintf("%s vs %s", target, reference)

# PCA: percent variance on both axes, sample names beside the points, a faint convex hull per condition when each has
# at least three samples, equal aspect so distances are not distorted.
hulls <- do.call(rbind, lapply(split(pca_points, pca_points$condition), function(p) if (nrow(p) >= 3) p[chull(p$PC1, p$PC2), ] else p[0, ]))
pca_plot <- ggplot(pca_points, aes(PC1, PC2, colour = condition)) +
  { if (all(table(pca_points$condition) >= 3)) geom_polygon(data = hulls, aes(fill = condition), alpha = 0.08, colour = NA) } +
  geom_point(size = 2.4) +
  geom_text_repel(aes(label = sample), size = 2.6, show.legend = FALSE, min.segment.length = 0.2, seed = 1) +
  scale_colour_manual(values = COND) + scale_fill_manual(values = COND, guide = "none") +
  coord_equal() +
  labs(x = sprintf("PC1 (%s%% of variance)", variance[1]), y = sprintf("PC2 (%s%% of variance)", variance[2]),
       title = "Principal components of variance-stabilised counts") +
  theme_locus() + theme(legend.position.inside = c(0.98, 0.02), legend.justification = c(1, 0))
save_figure("pca", pca_plot, 3.6, 3.4)

# Volcano and MA share three states and the same labelled genes.
tested$state <- factor(ifelse(!tested$significant, names(STATE)[1], ifelse(abs(tested$log2FoldChange) >= 1, names(STATE)[3], names(STATE)[2])), levels = names(STATE))
tested$symbol <- symbol(tested)
tested$neglog10padj <- -log10(pmax(tested$padj, 1e-300))
top <- head(tested[tested$significant, ], 12)
x_max <- max(abs(tested$log2FoldChange), 1.05)
volcano_plot <- ggplot(tested, aes(log2FoldChange, neglog10padj)) +
  geom_hline(yintercept = -log10(0.05), linetype = "22", linewidth = 0.3, colour = "#52514e") +
  geom_vline(xintercept = c(-1, 1), linetype = "22", linewidth = 0.3, colour = "#52514e") +
  geom_point(aes(colour = state), size = 0.9, alpha = 0.8, stroke = 0) +
  geom_text_repel(data = top, aes(label = symbol), size = 2.5, fontface = "italic", max.overlaps = 20, min.segment.length = 0.1,
                  segment.size = 0.25, segment.colour = "#52514e", seed = 1, box.padding = 0.25) +
  annotate("text", x = -x_max, y = -log10(0.05), label = "padj = 0.05", hjust = 0, vjust = -0.4, size = 2.3, colour = "#52514e") +
  annotate("text", x = c(-1, 1), y = -Inf, label = c("log2FC = −1", "log2FC = 1"), hjust = c(1.1, -0.1), vjust = -0.5, size = 2.3, colour = "#52514e") +
  scale_colour_manual(values = STATE, drop = FALSE) + scale_x_continuous(limits = c(-x_max, x_max)) +
  guides(colour = guide_legend(override.aes = list(size = 2, alpha = 1))) +
  labs(x = sprintf("log2 fold change (apeglm shrinkage)\n%s", contrast_label), y = "−log10 adjusted p-value (BH)",
       title = sprintf("%d of %d tested genes at padj < 0.05", sum(tested$significant), nrow(tested))) +
  theme_locus() + theme(legend.position.inside = c(0.98, 0.02), legend.justification = c(1, 0))
save_figure("volcano", volcano_plot, 3.6, 3.4)

ma_plot <- ggplot(tested, aes(baseMean, log2FoldChange)) +
  geom_hline(yintercept = 0, linewidth = 0.3, colour = "#52514e") +
  geom_point(aes(colour = state), size = 0.9, alpha = 0.8, stroke = 0) +
  geom_text_repel(data = top, aes(label = symbol), size = 2.5, fontface = "italic", max.overlaps = 20, min.segment.length = 0.1,
                  segment.size = 0.25, segment.colour = "#52514e", seed = 1, box.padding = 0.25) +
  scale_x_log10(labels = function(x) format(x, scientific = FALSE, trim = TRUE, big.mark = ",")) +
  scale_colour_manual(values = STATE, drop = FALSE) +
  guides(colour = guide_legend(override.aes = list(size = 2, alpha = 1))) +
  labs(x = "Mean of normalised counts (log10 scale)", y = sprintf("log2 fold change (apeglm shrinkage)\n%s", contrast_label), title = "MA plot") +
  theme_locus() + theme(legend.position.inside = c(0.98, 0.02), legend.justification = c(1, 0))
save_figure("ma", ma_plot, 3.6, 3.4)

# Sample-to-sample Euclidean distances on the variance-stabilised counts: replicates of one condition should cluster.
distances <- as.matrix(dist(t(assay(vsd))))
annotation <- data.frame(condition = samples$condition, row.names = samples$sample)
# pheatmap lays itself out for the open device, so each device is opened first and the heatmap drawn into it.
for (device in c("png", "pdf")) {
  path <- file.path(plots, paste0("sample_distance.", device))
  if (device == "png") png(path, width = 5.4, height = 4.2, units = "in", res = 300, bg = "white") else cairo_pdf(path, width = 5.4, height = 4.2, bg = "white")
  pheatmap(distances, color = colorRampPalette(BLUES)(64), border_color = "white",
           annotation_col = annotation, annotation_colors = list(condition = COND), annotation_names_col = FALSE,
           fontsize = 8, treeheight_row = 18, treeheight_col = 18, legend = TRUE,
           main = "Sample-to-sample distance (dark = close)")
  dev.off()
}

# Normalised counts of the six genes with the smallest adjusted p-value, one point per sample, grouped by condition.
top6 <- head(tested, 6)
long <- do.call(rbind, lapply(seq_len(nrow(top6)), function(i) data.frame(
  gene = top6$symbol[i], sample = colnames(normalized), condition = samples$condition[match(colnames(normalized), samples$sample)],
  count = normalized[top6$gene_id[i], ] + 0.5)))
long$gene <- factor(long$gene, levels = top6$symbol)
long$condition <- factor(long$condition, levels = c(reference, target))
gene_means <- aggregate(count ~ gene + condition, long, mean)
counts_plot <- ggplot(long, aes(condition, count, colour = condition)) +
  geom_crossbar(data = gene_means, aes(y = count, ymin = count, ymax = count), width = 0.5, linewidth = 0.3, colour = "#52514e") +
  geom_jitter(width = 0.12, height = 0, size = 1.8, alpha = 0.9) +
  facet_wrap(~gene, nrow = 2, scales = "free_y") +
  scale_y_log10() + scale_colour_manual(values = COND, guide = "none") +
  labs(x = NULL, y = "Normalised count + 0.5 (log10 scale)", title = "Six genes with the smallest adjusted p-value; bar = group mean") +
  theme_locus() + theme(axis.text.x = element_text(size = 7, angle = 20, hjust = 1), panel.spacing = unit(8, "pt"))
save_figure("top_genes_counts", counts_plot, 5.2, 3.6)

# The three legacy names stay at the top level (the web panel and the evidence folder link to them).
for (name in c("pca", "volcano", "ma")) file.copy(file.path(plots, paste0(name, ".png")), out_path(paste0(name, ".png")), overwrite = TRUE)

write_json(list(
  genes = nrow(counts), genes_tested = nrow(dds), genes_with_padj = nrow(tested),
  significant = sum(tested$significant), up = sum(tested$significant & tested$log2FoldChange > 0), down = sum(tested$significant & tested$log2FoldChange < 0),
  pca = list(variance = variance, means = means),
  versions = list(R = as.character(getRversion()), DESeq2 = as.character(packageVersion("DESeq2")), tximport = as.character(packageVersion("tximport")),
                  apeglm = as.character(packageVersion("apeglm")), ggplot2 = as.character(packageVersion("ggplot2")))
), out_path("deseq2_summary.json"), auto_unbox = TRUE, digits = NA, pretty = TRUE)
