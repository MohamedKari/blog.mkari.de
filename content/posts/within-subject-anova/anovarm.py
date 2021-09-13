import pandas as pd
import pingouin as pg
from pingouin import pairwise_ttests

from statsmodels.stats.anova import AnovaRM
from statsmodels.stats.multicomp import pairwise_tukeyhsd

def run():
    df = pd.read_csv("long-table.csv", sep=",")
    
    anova_results = pg.rm_anova(data=df, dv="Duration", subject="ParticipantId", within=["Distance", "Size"], detailed=True)
    pairwise_results = pairwise_ttests(dv='Duration', within="Distance", subject='ParticipantId', data=df, padjust="bonf")

    print(anova_results)
    print(pairwise_results)


def run_statsmodels():
    df = pd.read_csv("long-table.csv", sep=",")

    anova_rm = AnovaRM(df, "Duration", "ParticipantId", ["Distance", "Size"])
    anova_results = anova_rm.fit()
    pairwise_results = pairwise_tukeyhsd(df["Duration"], df["Distance"]) # statsmodels
    
    print(anova_results)
    print(pairwise_results)

if __name__ == "__main__":
    run()
