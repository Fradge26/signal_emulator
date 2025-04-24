from enum import IntEnum


class PhaseType(IntEnum):
    """
    Phase Type enum: names as defined on timing sheet, values as coded in Linsig v2.3.6
    """

    T = 1  # Traffic
    P = 2  # Pedestrian
    N = 2  # Special Pedestrian, Royal Mews horse phase for example
    F = 3  # Filter
    # term type 2 -> IA 4
    # term type 1 -> F 3
    D = 5  # Dummy


class LinsigPhaseType(IntEnum):
    TRAFFIC = 1
    PEDESTRIAN = 2
    FILTER = 3
    INDICATIVE_ARROW = 4
    DUMMY = 5
    DUMMY_WITH_RA = 6
    BUS = 7
    CYCLE = 8
    LRT = 9
    FILTER_WITH_CLOSING_AMBER = 10


class Cell(IntEnum):
    """
    Cell enum: names as defined in UTC, alternative longer names as used in SAD files
    """

    CNTR = 1
    NORT = 2
    EAST = 3
    SOUT = 4
    OUTR = 5
    CNTRA = 1
    NORTB = 2
    EAST_ = 3
    SOUTH = 4
    OUTER = 5


class PhaseTermType(IntEnum):
    """
    PhaseTermType: enum for defining the possible values of Phase Termination Type
    """

    END_OF_STAGE = 0
    ASSOCIATED_PHASE_GAINS_ROW = 1  # Filter
    ASSOCIATED_PHASE_LOSES_ROW = 2  # Indicative Arrow
    THREE = 3  # Unknown


PhaseTypeAndTermTypeToLinsigPhaseType = {
    (PhaseType.T, PhaseTermType.END_OF_STAGE): LinsigPhaseType.TRAFFIC,
    (PhaseType.P, PhaseTermType.END_OF_STAGE): LinsigPhaseType.PEDESTRIAN,
    (PhaseType.N, PhaseTermType.END_OF_STAGE): LinsigPhaseType.PEDESTRIAN,
    (PhaseType.F, PhaseTermType.ASSOCIATED_PHASE_GAINS_ROW): LinsigPhaseType.FILTER,
    (PhaseType.F, PhaseTermType.ASSOCIATED_PHASE_LOSES_ROW): LinsigPhaseType.INDICATIVE_ARROW,
    (PhaseType.D, PhaseTermType.END_OF_STAGE): LinsigPhaseType.DUMMY,
    (PhaseType.D, PhaseTermType.ASSOCIATED_PHASE_LOSES_ROW): LinsigPhaseType.DUMMY,
    (PhaseType.D, PhaseTermType.THREE): LinsigPhaseType.DUMMY,
    (PhaseType.T, PhaseTermType.ASSOCIATED_PHASE_GAINS_ROW): LinsigPhaseType.FILTER,
    # traffic phases with term type 1 assigned to Linsig FILTER type
    (PhaseType.F, PhaseTermType.END_OF_STAGE): LinsigPhaseType.DUMMY,
    # filter phase with term type 0 assigned to dummy as looks like an error
    (PhaseType.T, PhaseTermType.ASSOCIATED_PHASE_LOSES_ROW): LinsigPhaseType.TRAFFIC,
    # traffic phase with term type 2 assigned to traffic, these are generally cycle signals with early release
}


class M37StageToStageNumber(IntEnum):
    G1 = 1
    G2 = 2
    G3 = 3
    G4 = 4
    G5 = 5
    G6 = 6
    G7 = 7
    G8 = 8
    GX = 1
    PG = 2


class PedBitsToStageNumber(IntEnum):
    PV = 1
    PX = 2
